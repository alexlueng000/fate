# app/chat/deepseek_client.py
import os
import json
import time
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


def call_deepseek(messages: List[Dict[str, str]], model: Optional[str] = None) -> str:
    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": model or DEEPSEEK_MODEL,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 8192
    }
    last_exc: Exception = RuntimeError("未知错误")
    for attempt in range(_RETRY_TIMES):
        try:
            r = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=300)
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
        except Exception as e:
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
    payload = {
        "model": model or DEEPSEEK_MODEL,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 8192,
        "stream": True,
    }
    last_exc: Exception = RuntimeError("未知错误")
    for attempt in range(_RETRY_TIMES):
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
                        delta = obj.get("choices", [{}])[0].get("delta", {})
                        if "content" in delta and delta["content"]:
                            yield delta["content"]
                    except Exception:
                        yield data
            return  # 成功结束，不再重试
        except Exception as e:
            last_exc = e
            if attempt < _RETRY_TIMES - 1:
                time.sleep(_RETRY_DELAY)
    raise last_exc
