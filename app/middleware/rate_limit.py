# app/middleware/rate_limit.py
"""
简单的 IP 速率限制中间件
"""
import time
from collections import defaultdict
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware

class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_requests: int = 10, window_seconds: int = 60):
        super().__init__(app)
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests = defaultdict(list)  # IP -> [timestamp, timestamp, ...]

    async def dispatch(self, request: Request, call_next):
        # 只限制 /api/chat 路径
        if not request.url.path.startswith("/api/chat"):
            return await call_next(request)

        # 获取客户端 IP
        client_ip = request.client.host
        if "x-forwarded-for" in request.headers:
            client_ip = request.headers["x-forwarded-for"].split(",")[0].strip()

        now = time.time()

        # 清理过期记录
        self.requests[client_ip] = [
            ts for ts in self.requests[client_ip]
            if now - ts < self.window_seconds
        ]

        # 检查是否超限
        if len(self.requests[client_ip]) >= self.max_requests:
            raise HTTPException(
                status_code=429,
                detail=f"请求过于频繁，请 {self.window_seconds} 秒后再试"
            )

        # 记录本次请求
        self.requests[client_ip].append(now)

        response = await call_next(request)
        return response
