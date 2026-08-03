import asyncio

from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks
from fastapi import Header, Body
from helper import verify_auth, custom_http_exception_handler
from provider import run_mock_provider


import time
import json
import hashlib


# CONFIG
VERSION = "1.0"
MAXPAYLOADBYTES = 1048576
CHUNKBYTES = 65536
MAXCONCURRENTJOBS = 4
RATELIMITPERMINUTE = 30
VALID_TOKEN = "secret"


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
    if not any(line.startswith(("diff --git", "+++ ", "--- ")) for line in diff_text.splitlines()):
        return False
    return True

def validate_request(content: dict):
    diff = content.get("diff")
    if not diff or not is_valid_diff(diff):
        raise HTTPException(422, detail={"code": "invalid_diff", "message": "diff missing, empty, or unparseable"})
    return diff, content.get("options", {})


sem = asyncio.Semaphore(4) # Limit concurrent jobs to 4
async def run_job(job_id):
    async with sem:
        jobs[job_id]["status"] = "running"
        diff = jobs[job_id]["diff"]
        findings = run_mock_provider(diff)
        jobs[job_id]["findings"] = findings
        jobs[job_id]["status"] = "done"
        jobs[job_id]["findings"] = findings  # Store findings in cache for future retrieval


# MAIN
app = FastAPI()
app.add_exception_handler(HTTPException, custom_http_exception_handler)



@app.get("/health")
async def health_check():
    return { "status": "ok", "version": VERSION, "uptimeSeconds": int(time.time() - start_time) }


@app.get("/spec")
async def get_spec():
    return {
    "specVersion": "1.0",
    "providers": ["mock", "llm"],
    "limits": {
        "maxPayloadBytes": MAXPAYLOADBYTES,
        "chunkBytes": CHUNKBYTES,
        "maxConcurrentJobs": MAXCONCURRENTJOBS,
        "rateLimitPerMinute": RATELIMITPERMINUTE
    }
}


@app.post("/v1/reviews", status_code=202, dependencies=[Depends(verify_auth)])
async def post_review(content: dict = Body(...), 
                      idempotent_key: str = Header(None, alias="Idempotency-Key"),
                      background_tasks: BackgroundTasks = None):
    
    diff, options = validate_request(content)

    hash_input = diff + json.dumps(options, sort_keys=True)
    job_id = hashlib.sha256(hash_input.encode()).hexdigest()

    if job_id not in jobs:
        jobs[job_id] = {
            "jobId": job_id,
            "status": "queued",
            "diff": diff,
            "options": options,
            "findings": [],
            "usage": {"inputBytes": len(diff.encode()), "chunks": 0, "cacheHit": False},
        }
        background_tasks.add_task(run_job, job_id)
    else:
        jobs[job_id]["usage"]["cacheHit"] = True  # not finalized yet

    if idempotent_key:
        idempotency_keys[idempotent_key] = job_id

    return {"jobId": job_id, "status": jobs[job_id]["status"]}



@app.get("/v1/reviews/{job_id}", dependencies=[Depends(verify_auth)])
async def get_review(job_id: str):
    # Placeholder implementation - replace with actual job status retrieval logic
    if job_id in jobs:
        return {"jobId": job_id, "status": jobs[job_id]["status"]}
    else:
        raise HTTPException(status_code=404, detail="Job not found")