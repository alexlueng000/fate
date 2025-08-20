import time, hmac, hashlib, base64, json
from typing import Any

def jwt_encode(payload: dict, secret: str, alg: str = "HS256", exp_minutes: int = 60*24*7) -> str:
    header = {"typ": "JWT", "alg": alg}
    now = int(time.time())
    payload = {**payload, "iat": now, "exp": now + exp_minutes*60}
    def b64(x: bytes) -> str:
        return base64.urlsafe_b64encode(x).rstrip(b"=").decode()
    header_b64 = b64(json.dumps(header, separators=(",", ":")).encode())
    payload_b64 = b64(json.dumps(payload, separators=(",", ":")).encode())
    signing = f"{header_b64}.{payload_b64}".encode()
    sig = hmac.new(secret.encode(), signing, hashlib.sha256).digest()
    return f"{header_b64}.{payload_b64}.{b64(sig)}"