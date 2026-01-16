# app/utils/encryption.py
import os
import json
import base64
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from app.config import settings

def _get_key() -> bytes:
    """获取32字节加密密钥"""
    key = settings.chart_encryption_key.encode()[:32]
    return key.ljust(32, b'\0')

def encrypt_data(data: dict) -> str:
    """加密字典数据，返回 base64 编码的密文"""
    aesgcm = AESGCM(_get_key())
    nonce = os.urandom(12)
    plaintext = json.dumps(data, ensure_ascii=False).encode('utf-8')
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)
    return base64.b64encode(nonce + ciphertext).decode('utf-8')

def decrypt_data(encrypted: str) -> dict:
    """解密 base64 编码的密文，返回字典"""
    aesgcm = AESGCM(_get_key())
    raw = base64.b64decode(encrypted)
    nonce = raw[:12]
    ciphertext = raw[12:]
    plaintext = aesgcm.decrypt(nonce, ciphertext, None)
    return json.loads(plaintext.decode('utf-8'))
