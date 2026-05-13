# app/chat/deepseek_client.py
from __future__ import annotations

import json
import os
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from typing import Dict, Iterator, List, Optional

import requests
from dotenv import load_dotenv

from app.config import settings

load_dotenv()

DEEPSEEK_API_KEY = settings.deepseek_api_key
DEEPSEEK_API_URL = settings.deepseek_api_url
DEEPSEEK_MODEL = settings.deepseek_model

PROMPT_LOG_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "logs", "prompts")
)
os.makedirs(PROMPT_LOG_DIR, exist_ok=True)

_RETRY_TIMES = max(1, settings.deepseek_retry_times)
_RETRY_BASE_DELAY = max(0.1, settings.deepseek_retry_base_delay)
_REQUEST_TIMEOUT = settings.deepseek_timeout
_ACQUIRE_TIMEOUT = max(1, settings.deepseek_acquire_timeout)
_CONCURRENCY_LIMIT = max(1, settings.deepseek_max_concurrent)
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
_semaphore = threading.BoundedSemaphore(_CONCURRENCY_LIMIT)

_caller_var = threading.local()


class DeepSeekBusyError(RuntimeError):
    """Raised when all DeepSeek request slots are occupied."""


class DeepSeekConfigError(RuntimeError):
    """Raised when required DeepSeek configuration is missing."""


def set_caller(name: str):
    """Set the logical caller name for logging in the current thread."""
    _caller_var.name = name


def _get_caller() -> str:
    return getattr(_caller_var, "name", "unknown")


def _ensure_api_key() -> str:
    if not DEEPSEEK_API_KEY:
        raise DeepSeekConfigError("DEEPSEEK_API_KEY is not configured")
    return DEEPSEEK_API_KEY


@contextmanager
def _deepseek_slot():
    acquired = _semaphore.acquire(timeout=_ACQUIRE_TIMEOUT)
    if not acquired:
        raise DeepSeekBusyError("AI service is busy; please try again later")
    try:
        yield
    finally:
        _semaphore.release()


def _retry_delay(response: Optional[requests.Response], attempt: int) -> float:
    if response is not None:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return max(0.1, float(retry_after))
            except ValueError:
                pass
    return _RETRY_BASE_DELAY * (2 ** attempt)


def _should_retry(response: Optional[requests.Response], attempt: int) -> bool:
    if attempt >= _RETRY_TIMES - 1:
        return False
    if response is None:
        return True
    return response.status_code in _RETRYABLE_STATUS_CODES


def _log_prompt_to_file(messages: List[Dict[str, str]], model: str, caller: str):
    """Write the outbound prompt to a local audit log."""
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        safe_caller = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in caller)
        safe_model = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in model)
        log_filename = f"{timestamp}_{safe_caller}_{safe_model}.json"
        log_path = os.path.join(PROMPT_LOG_DIR, log_filename)

        log_data = {
            "timestamp": datetime.now().isoformat(),
            "caller": caller,
            "model": model,
            "messages": messages,
            "message_count": len(messages),
            "total_chars": sum(len(msg.get("content", "")) for msg in messages),
        }

        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(log_data, f, ensure_ascii=False, indent=2)

        txt_path = log_path.replace(".json", ".txt")
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write("=== DeepSeek API Call Log ===\n")
            f.write(f"Timestamp: {log_data['timestamp']}\n")
            f.write(f"Caller: {caller}\n")
            f.write(f"Model: {model}\n")
            f.write(f"Message Count: {len(messages)}\n")
            f.write(f"Total Characters: {log_data['total_chars']}\n")
            f.write(f"\n{'=' * 80}\n\n")

            for i, msg in enumerate(messages, 1):
                role = msg.get("role", "unknown")
                content = msg.get("content", "")
                f.write(f"[Message {i}] Role: {role}\n")
                f.write(f"{'-' * 80}\n")
                f.write(f"{content}\n")
                f.write(f"\n{'=' * 80}\n\n")
    except Exception as e:
        from app.core.logging import get_logger

        logger = get_logger("deepseek_client")
        logger.warning(f"Failed to write prompt log: {e}")


def _log_api_call(
    model: str,
    stream: bool,
    prompt_tokens: int,
    completion_tokens: int,
    latency: float,
    success: bool,
    attempt: int,
    error: Optional[str] = None,
    prompt_cache_hit_tokens: int = 0,
    prompt_cache_miss_tokens: int = 0,
):
    """Write API usage logs asynchronously without blocking user responses."""
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
                    prompt_cache_hit_tokens=prompt_cache_hit_tokens,
                    prompt_cache_miss_tokens=prompt_cache_miss_tokens,
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
            pass

    threading.Thread(target=_write, daemon=True).start()


def call_deepseek(messages: List[Dict[str, str]], model: Optional[str] = None) -> str:
    api_key = _ensure_api_key()
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    use_model = model or DEEPSEEK_MODEL
    caller = _get_caller()

    _log_prompt_to_file(messages, use_model, caller)

    payload = {
        "model": use_model,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 8192,
    }

    last_exc: Exception = RuntimeError("Unknown DeepSeek error")
    with _deepseek_slot():
        for attempt in range(_RETRY_TIMES):
            t0 = time.perf_counter()
            response: Optional[requests.Response] = None
            try:
                response = requests.post(
                    DEEPSEEK_API_URL,
                    headers=headers,
                    json=payload,
                    timeout=_REQUEST_TIMEOUT,
                )
                response.raise_for_status()
                data = response.json()
                latency = time.perf_counter() - t0
                usage = data.get("usage", {})
                _log_api_call(
                    model=use_model,
                    stream=False,
                    prompt_tokens=usage.get("prompt_tokens", 0),
                    completion_tokens=usage.get("completion_tokens", 0),
                    prompt_cache_hit_tokens=usage.get("prompt_cache_hit_tokens", 0),
                    prompt_cache_miss_tokens=usage.get("prompt_cache_miss_tokens", 0),
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
                if _should_retry(response, attempt):
                    time.sleep(_retry_delay(response, attempt))

    raise last_exc


def call_deepseek_stream(messages: List[Dict[str, str]], model: Optional[str] = None) -> Iterator[str]:
    """
    Yield incremental content from DeepSeek's OpenAI-compatible SSE response.
    Retries happen only before any content has been yielded to avoid duplicates.
    """
    api_key = _ensure_api_key()
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    use_model = model or DEEPSEEK_MODEL
    caller = _get_caller()

    _log_prompt_to_file(messages, use_model, caller)

    payload = {
        "model": use_model,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 8192,
        "stream": True,
        "stream_options": {"include_usage": True},
    }

    last_exc: Exception = RuntimeError("Unknown DeepSeek streaming error")
    with _deepseek_slot():
        has_yielded = False
        for attempt in range(_RETRY_TIMES):
            t0 = time.perf_counter()
            success = False
            prompt_tokens = 0
            completion_tokens = 0
            prompt_cache_hit_tokens = 0
            prompt_cache_miss_tokens = 0
            error: Optional[str] = None
            response: Optional[requests.Response] = None

            try:
                with requests.post(
                    DEEPSEEK_API_URL,
                    headers=headers,
                    json=payload,
                    stream=True,
                    timeout=_REQUEST_TIMEOUT,
                ) as r:
                    response = r
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
                                prompt_tokens = usage.get("prompt_tokens", 0)
                                completion_tokens = usage.get("completion_tokens", 0)
                                prompt_cache_hit_tokens = usage.get("prompt_cache_hit_tokens", 0)
                                prompt_cache_miss_tokens = usage.get("prompt_cache_miss_tokens", 0)

                            choices = obj.get("choices") or []
                            first_choice = choices[0] if choices else None
                            if not first_choice:
                                continue

                            delta = first_choice.get("delta") or {}
                            content = delta.get("content")
                            if content:
                                has_yielded = True
                                yield content
                        except Exception as parse_err:
                            from app.core.logging import get_logger

                            logger = get_logger("deepseek_client")
                            logger.warning(f"Failed to parse SSE chunk: {parse_err}, data: {data[:200]}")
                            continue
                success = True
                return
            except Exception as e:
                error = str(e)
                last_exc = e
            finally:
                _log_api_call(
                    model=use_model,
                    stream=True,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    prompt_cache_hit_tokens=prompt_cache_hit_tokens,
                    prompt_cache_miss_tokens=prompt_cache_miss_tokens,
                    latency=round(time.perf_counter() - t0, 3),
                    success=success,
                    attempt=attempt,
                    error=error,
                )

            if has_yielded:
                break
            if _should_retry(response, attempt):
                time.sleep(_retry_delay(response, attempt))

    raise last_exc
