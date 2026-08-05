# SUBMISSION.md

## Architecture

- FastAPI service with in-memory job storage (no database)
- Requests are queued synchronously and processing runs as an async background task
- Concurrency capped at 4 simultaneous jobs via `asyncio.Semaphore`
- `jobId = sha256(diff + options)` — identical `{diff, options}` always resolves to the same job

**Files:**
- `main.py` — FastAPI app, route definitions, request-parsing helpers
- `helper.py` — auth, validation, exception handlers
- `provider.py` — mock rule engine + LLM provider

## Provider Design

- **mock**: pure regex/string matching against the fixed rule table. Diffs are chunked on file boundaries (≤64KiB per chunk, files >64KiB become their own chunk) so large diffs process correctly; findings from all chunks are merged, deduped by `id`, and sorted before returning.
- **llm**: Google Gemini (`gemini-3.6-flash`) via the `google-genai` SDK. No chunking — full diff sent in one call, given the task's minimal-viability bar for this path. The call is wrapped in `asyncio.to_thread` so the main thread is freed for other requests while a review is in progress. Any failure (missing key, network error, malformed model output) propagates up and is caught by `run_job`'s exception handler, producing a clean `failed` job.

## Verifying Cross-Cutting Behaviors

- **Chunking**: temporarily downscaled `CHUNKBYTES` from 64KiB to 1KiB to trigger multi-chunk processing with small test diffs; confirmed `usage.chunks > 1`, with correct behaviour.
- **Caching + idempotency**: tested all key/body combinations — same key + same body (same jobId returned), same key + different body (`409 idempotency_conflict`), different key + same body (same jobId via content-hash caching, no conflict).
- **SSE replay**: confirmed replay of a finished job's. Added a temporary artificial delay(`asyncio.sleep(10)`) in `run_job` to force a live-connection window, and confirmed events stream while a job is still processing.
- **Concurrency**: fired 9 simultaneous jobs via script. Confirmed a max of 4 jobs `running` at any moment (matching the semaphore limit), remaining jobs correctly `queued`.
- **Rate limiting**: downscaled to 5/minute for testing, fired 10 rapid requests, confirmed clean `429` responses and `Retry-After`.

## AI Tools Used

Claude (free tier) — used throughout for:
- Architecture and design discussion
- Debugging
- Code generation with manual review/verification of each piece
- Testing and edge-case identification

## AI Suggestion I Rejected

The AI suggested me to just throw an error when `provider="llm"` to show it fails gracefully. I insisted on using proper LLM API call since it's part of the marking evaluation and is not soo hard to configure.

## What I'd Do With More Time

- `llm` provider with chunking that can handle diffs exceeding the model's context window
- Persistent storage (Redis or a database) instead of in-memory storage, so data survives restarts
- Priority for diffs ≤64KiB, to try to guarantee the 30s latency budget(since diffs >64KiB don't have latency budget)
- allow same diff, different options(mainly maxFindings) to reuse findings from previous same diff job