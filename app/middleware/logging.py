# app/middleware/logging.py
"""
请求日志中间件

记录每个 HTTP 请求的详细信息，包括：
- 请求 ID（用于链路追踪）
- 请求方法、路径、查询参数
- 客户端 IP、User-Agent
- 响应状态码、耗时
"""
import time
import uuid
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from app.core.logging import get_logger

logger = get_logger("access")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # 生成请求 ID
        request_id = str(uuid.uuid4())[:8]
        request.state.request_id = request_id

        # 记录开始时间
        start_time = time.time()

        # 请求信息
        log_data = {
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "query": str(request.query_params),
            "client_ip": request.client.host if request.client else "unknown",
            "user_agent": request.headers.get("user-agent", "")[:100],
        }

        try:
            response = await call_next(request)

            # 计算耗时
            duration_ms = (time.time() - start_time) * 1000

            log_data.update({
                "status_code": response.status_code,
                "duration_ms": round(duration_ms, 2),
            })

            # 根据状态码选择日志级别
            if response.status_code >= 500:
                logger.error("request_completed", **log_data)
            elif response.status_code >= 400:
                logger.warning("request_completed", **log_data)
            else:
                logger.info("request_completed", **log_data)

            return response

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            log_data.update({
                "status_code": 500,
                "duration_ms": round(duration_ms, 2),
                "error": str(e),
                "error_type": type(e).__name__,
            })
            logger.exception("request_failed", **log_data)
            raise
