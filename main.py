import asyncio

from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks
from fastapi import Header, Body, Request
from fastapi.responses import StreamingResponse
from fastapi.exceptions import RequestValidationError
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded

from helper import verify_auth, custom_http_exception_handler, custom_request_validation_error_handler, custom_rate_limit_handler
from provider import run_mock_provider_chunked, run_llm_provider_chunked
from provider import CHUNKBYTES


import time
import json
import hashlib


# CONFIG
VERSION = "1.0"
MAXPAYLOADBYTES = 1048576
MAXCONCURRENTJOBS = 4
RATELIMITPERMINUTE = 30


# STATE
start_time = time.time()
idempotency_keys = {}
jobs = {}


# HELPER

def is_valid_diff(diff_text):
    # Basic validation: check if diff_text is a non-empty string
    if not isinstance(diff_text, str) or not diff_text.strip():
        return False
    # Check for the presence of at least one file change indicator
    # does it contain at least one `+++`/`---` line or `@@` hunk header — reject otherwise.
    if not any(line.startswith(("diff --git", "+++ ", "--- ", "@@ ")) for line in diff_text.splitlines()):
        return False
    return True

def validate_request(content: dict):
    diff = content.get("diff")
    if diff and len(diff.encode()) > MAXPAYLOADBYTES:
        raise HTTPException(413, detail={"code": "payload_too_large", "message": "diff exceeds maximum allowed size of 1MiB"})
    if not diff or not is_valid_diff(diff):
        raise HTTPException(422, detail={"code": "invalid_diff", "message": "diff missing, empty, or unparseable"})
    return diff, content.get("options", {})

'''
EXPECTED FORMAT
{
  "diff": "<unified diff, required>",
  "options": {
    "provider": "mock" | "llm",     // default "mock"
    "maxFindings": <int, default 100>
  }
}
'''
sem = asyncio.Semaphore(4) # Limit concurrent jobs to 4
async def run_job(job_id):
    async with sem:
        jobs[job_id]["status"] = "running"

        try:
            diff = jobs[job_id]["diff"]
            provider = jobs[job_id]["options"].get("provider", "mock")
                
            if provider == "mock":
                findings, chunk_stats = run_mock_provider_chunked(diff, max_findings=jobs[job_id]["options"].get("maxFindings", 100))
            elif provider == "llm":
                findings, chunk_stats = await run_llm_provider_chunked(diff, max_findings=jobs[job_id]["options"].get("maxFindings", 100))

            for finding in findings:
                jobs[job_id]["events"].append({"event": "finding", "data": finding})

            jobs[job_id]["findings"] = findings
            jobs[job_id]["usage"]["chunks"] = chunk_stats["chunks"]
            jobs[job_id]["status"] = "done"
            jobs[job_id]["events"].append({"event": "status", "data": {"status": "done"}})
            jobs[job_id]["events"].append({"event": "done", "data": {"total": len(findings), "usage": jobs[job_id]["usage"]}})

        except Exception as e:
            jobs[job_id]["error"] = str(e)
            jobs[job_id]["status"] = "failed"
            jobs[job_id]["events"].append({"event": "status", "data": {"status": "failed"}})


def get_token_key(request: Request):
    auth_header = request.headers.get("Authorization", "")
    return auth_header  # or strip "Bearer " prefix if you want just the token itself
# Initialize Limiter
limiter = Limiter(key_func=get_token_key)

'''
Server-Sent Events (Content-Type: text/event-stream):

event status — at least on status transitions.
event finding — one per finding, as discovered.
event done — {"total": <count>, "usage": {...}}, then close.
Connecting to a finished job's stream must replay all events identically.
'''


# MAIN
app = FastAPI()

app.add_exception_handler(HTTPException, custom_http_exception_handler)
app.add_exception_handler(RequestValidationError, custom_request_validation_error_handler)
# Register the error handler
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, custom_rate_limit_handler)


@app.get("/health")
async def health_check():
    return { "status": "ok", "version": VERSION, "uptimeSeconds": int(time.time() - start_time) }


@app.get("/spec")
async def get_spec():
    return {
    "specVersion": VERSION,
    "providers": ["mock", "llm"],
    "limits": {
        "maxPayloadBytes": MAXPAYLOADBYTES,
        "chunkBytes": CHUNKBYTES,
        "maxConcurrentJobs": MAXCONCURRENTJOBS,
        "rateLimitPerMinute": RATELIMITPERMINUTE
    }
}


# rate limiting 30 submission/minute. respond 429 with a Retry-After header and the error envelope. Never 5xx under burst.
@app.post("/v1/reviews", status_code=202, dependencies=[Depends(verify_auth)])
@limiter.limit(f"{RATELIMITPERMINUTE}/minute")
async def post_review(content: dict = Body(...), 
                      idempotent_key: str = Header(None, alias="Idempotency-Key"),
                      background_tasks: BackgroundTasks = None, 
                      request: Request = None):
    
    diff, options = validate_request(content)

    hash_input = diff + json.dumps(options, sort_keys=True)
    job_id = hashlib.sha256(hash_input.encode()).hexdigest()


    if idempotent_key in idempotency_keys:
        if idempotency_keys[idempotent_key] != job_id:
            raise HTTPException(status_code=409, detail={"code": "idempotency_conflict", "message": "Idempotency key conflict"})

    provider = options.get("provider", "mock")
    if provider not in ["mock", "llm"]:
        provider = "mock"

    if job_id not in jobs:
        jobs[job_id] = {
            "jobId": job_id,
            "status": "queued",
            "diff": diff,
            "options": {**options, "provider": provider},  # keep everything, just normalize provider
        "findings": [],
        "usage": {"inputBytes": len(diff.encode()), "chunks": 0, "cacheHit": False},
        "events": [{"event": "status", "data": {"status": "queued"}}]  # store events for streaming
        }
        background_tasks.add_task(run_job, job_id)
    else:
       jobs[job_id]["usage"]["cacheHit"] = True

    if idempotent_key:
        idempotency_keys[idempotent_key] = job_id

    return {"jobId": job_id, "status": jobs[job_id]["status"]}



'''
FORMAT
{
  "jobId": "...",
  "status": "queued" | "running" | "done" | "failed",
  "findings": [ ... ],          // when done
  "usage": { "inputBytes": <int>, "chunks": <int>, "cacheHit": <bool> }
}
'''

@app.get("/v1/reviews/{job_id}", dependencies=[Depends(verify_auth)])
async def get_review(job_id: str):
    if job_id in jobs:
        return {"jobId": job_id,
                "status": jobs[job_id]["status"],
                "findings": jobs[job_id].get("findings"),
                "usage": jobs[job_id].get("usage"),
                "error": jobs[job_id].get("error")
                }
    else:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Unknown jobId"})


@app.get("/v1/reviews/{job_id}/stream", dependencies=[Depends(verify_auth)])
async def stream_review(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Unknown jobId"})

    async def event_generator():
        # Replay all events for this job
        for event in jobs[job_id]["events"]:
            yield f"event: {event['event']}\ndata: {json.dumps(event['data'])}\n\n"
        # Keep the connection open until the job is done
        while jobs[job_id]["status"] not in ["done", "failed"]:
            await asyncio.sleep(1)
            # Check for new events
            for event in jobs[job_id]["events"]:
                yield f"event: {event['event']}\ndata: {json.dumps(event['data'])}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

