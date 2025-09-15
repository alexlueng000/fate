# app/chat/sse.py
from typing import Iterator, Callable
from fastapi import Request
from fastapi.responses import StreamingResponse

def should_stream(req: Request) -> bool:
    accept = (req.headers.get("accept") or "").lower()
    if "text/event-stream" in accept:
        return True
    q = req.query_params.get("stream")
    if q and q.lower() in ("1", "true", "yes", "y"):
        return True
    return False

def sse_pack(data: str) -> bytes:
    return f"data: {data}\n\n".encode("utf-8")

def sse_response(gen: Callable[[], Iterator[bytes]]) -> StreamingResponse:
    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    return StreamingResponse(gen(), media_type="text/event-stream", headers=headers)
