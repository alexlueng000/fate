# app/chat/deepseek_client.py
import os
import json
import requests
from typing import Dict, List, Iterator, Any
from dotenv import load_dotenv

load_dotenv()

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL   = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

def call_deepseek(messages: List[Dict[str, str]]) -> str:
    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 800
    }
    # print("call_deepseek", payload)
    r = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=60)
    r.raise_for_status()
    data = r.json()
    # print("call_deepseek", data)
    return data["choices"][0]["message"]["content"]

def call_deepseek_stream(messages: List[Dict[str, str]]) -> Iterator[str]:
    """
    边读边 yield 文本增量；兼容 OpenAI SSE：每行 'data: {...}'，我们只提取 delta.content。
    """
    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 800,
        "stream": True,
    }
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
                # 上游偶发非 JSON，直接透传
                yield data
