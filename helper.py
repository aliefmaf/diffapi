from fastapi import Header, HTTPException
from fastapi.responses import JSONResponse


VALID_TOKEN = "secret"


async def custom_http_exception_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail}   # exc.detail should just be {"code": ..., "message": ...}
    )

async def custom_request_validation_error_handler(request, exc):
    # This handler is for validation errors raised by FastAPI (e.g., missing headers, invalid types)
    return JSONResponse(
        status_code=400,
        content={"error": {"code": "invalid_json", "message": "Request body is not valid JSON"}}
    )

async def custom_rate_limit_handler(request, exc):
    return JSONResponse(
        status_code=429,
        content={"error": {"code": "rate_limited", "message": "Too many requests"}},
        headers={"Retry-After": "60"}
    )


async def verify_auth(authorization: str = Header(None)):
    if authorization != f"Bearer {VALID_TOKEN}":
        raise HTTPException(status_code=401, detail={"code": "unauthorized", "message": "Invalid or missing token"})



# usage: raise HTTPException(status_code=401, detail={"code": "unauthorized", "message": "Invalid or missing token"})