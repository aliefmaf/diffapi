from fastapi import Header, HTTPException, JSONResponse
from main import VALID_TOKEN


async def custom_http_exception_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail}   # exc.detail should just be {"code": ..., "message": ...}
    )

async def verify_auth(authorization: str = Header(None)):
    if authorization != f"Bearer {VALID_TOKEN}":
        raise HTTPException(status_code=401, detail={"code": "unauthorized", "message": "Invalid or missing token"})



# usage: raise HTTPException(status_code=401, detail={"code": "unauthorized", "message": "Invalid or missing token"})