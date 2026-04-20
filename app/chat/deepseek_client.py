# app/chat/deepseek_client.py
import os
import json
import time
import threading
import requests
from typing import Dict, List, Iterator, Any, Optional
from dotenv import load_dotenv

load_dotenv()

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
# 全局默认模型，如果环境变量未设置，使用 deepseek-chat
DEEPSEEK_MODEL   = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

_RETRY_TIMES = 3
_RETRY_DELAY = 2  # 秒

# ---- 调用方标识（上层通过 _caller 线程变量传入） ----
_caller_var = threading.local()


def set_caller(name: str):
    """由上层在调用前设置，用于标记调用来源"""
    _caller_var.name = name


def _get_caller() -> str:
    return getattr(_caller_var, "name", "unknown")


def _log_api_call(
    model: str,
    stream: bool,
    prompt_tokens: int,
    completion_tokens: int,
    latency: float,
    success: bool,
    attempt: int,
    error: Optional[str] = None,
):
    """异步写入 api_call_logs 表，不阻塞主流程"""
    caller = _get_caller()

    def _write():
        try:
            from app.db import SessionLocal
            from app.models.api_call_log import ApiCallLog
            db = SessionLocal()
            try:
                log = ApiCallLog(
                    model=model,
                    caller=caller,
                    stream=stream,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    latency=round(latency, 3),
                    success=success,
                    attempt=attempt,
                    error=error[:500] if error else None,
                )
                db.add(log)
                db.commit()
            finally:
                db.close()
        except Exception:
            pass  # 日志写入失败不影响主流程

    threading.Thread(target=_write, daemon=True).start()


def call_deepseek(messages: List[Dict[str, str]], model: Optional[str] = None) -> str:
    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
    use_model = model or DEEPSEEK_MODEL
    payload = {
        "model": use_model,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 8192
    }
    last_exc: Exception = RuntimeError("未知错误")
    for attempt in range(_RETRY_TIMES):
        t0 = time.perf_counter()
        try:
            r = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=300)
            r.raise_for_status()
            data = r.json()
            latency = time.perf_counter() - t0
            # 提取 token 用量
            usage = data.get("usage", {})
            _log_api_call(
                model=use_model,
                stream=False,
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                latency=latency,
                success=True,
                attempt=attempt,
            )
            return data["choices"][0]["message"]["content"]
        except Exception as e:
            latency = time.perf_counter() - t0
            _log_api_call(
                model=use_model,
                stream=False,
                prompt_tokens=0,
                completion_tokens=0,
                latency=latency,
                success=False,
                attempt=attempt,
                error=str(e),
            )
            last_exc = e
            if attempt < _RETRY_TIMES - 1:
                time.sleep(_RETRY_DELAY)
    raise last_exc


def call_deepseek_stream(messages: List[Dict[str, str]], model: Optional[str] = None) -> Iterator[str]:
    """
    边读边 yield 文本增量；兼容 OpenAI SSE：每行 'data: {...}'，我们只提取 delta.content。
    网络抖动时最多重试 _RETRY_TIMES 次。
    """
    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
    use_model = model or DEEPSEEK_MODEL
    payload = {
        "model": use_model,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 8192,
        "stream": True,
        "stream_options": {"include_usage": True},  # 让 DeepSeek 在末尾 chunk 返回完整 usage
    }
    last_exc: Exception = RuntimeError("未知错误")
    for attempt in range(_RETRY_TIMES):
        t0 = time.perf_counter()
        _logged = False      # 防止 finally 和 except 双重记录
        _success = False
        _prompt_tokens = 0
        _completion_tokens = 0
        _error: Optional[str] = None
        try:
            with requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, stream=True, timeout=300) as r:
                r.raise_for_status()
                for raw_line in r.iter_lines(decode_unicode=True):
                    if not raw_line:
                        continue
                    line = raw_line.strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if not data or data == "[DONE]":
                        continue
                    try:
                        obj = json.loads(data)
                        usage = obj.get("usage") or {}
                        if usage:
                            _prompt_tokens = usage.get("prompt_tokens", 0)
                            _completion_tokens = usage.get("completion_tokens", 0)
                        choices = obj.get("choices") or []
                        first_choice = choices[0] if choices else None
                        if not first_choice:
                            continue
                        delta = first_choice.get("delta") or {}
                        if "content" in delta and delta["content"]:
                            yield delta["content"]
                    except Exception as parse_err:
                        # Log parsing errors but don't yield raw data
                        from app.core.logging import get_logger
                        logger = get_logger("deepseek_client")
                        logger.warning(f"Failed to parse SSE chunk: {parse_err}, data: {data[:200]}")
                        continue
            _success = True
            return  # 成功结束，不再重试
        except Exception as e:
            _error = str(e)
            last_exc = e
        finally:
            # 无论正常结束、异常、还是客户端断连(GeneratorExit)都会执行
            if not _logged:
                _logged = True
                _log_api_call(
                    model=use_model,
                    stream=True,
                    prompt_tokens=_prompt_tokens,
                    completion_tokens=_completion_tokens,
                    latency=round(time.perf_counter() - t0, 3),
                    success=_success,
                    attempt=attempt,
                    error=_error,
                )
        if attempt < _RETRY_TIMES - 1:
            time.sleep(_RETRY_DELAY)
    raise last_exc
