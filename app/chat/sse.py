# app/chat/sse.py
import json
from typing import Iterator, Callable, Union, Dict, Any
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

def sse_pack(data: Union[str, Dict[str, Any]]) -> bytes:
    """
    Pack data into SSE format.

    Args:
        data: String or dict to send. Dicts are JSON-serialized.

    Returns:
        Encoded SSE message
    """
    if isinstance(data, dict):
        data = json.dumps(data, ensure_ascii=False)
    return f"data: {data}\n\n".encode("utf-8")

def sse_response(gen: Callable[[], Iterator[bytes]]) -> StreamingResponse:
    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    return StreamingResponse(gen(), media_type="text/event-stream", headers=headers)
