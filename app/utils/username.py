# utils/username.py
import re
import random
import string

def slugify_username(nickname: str | None, prefix: str = "mp") -> str:
    """
    把昵称变成 username 基底：
    - 去掉 emoji / 非字母数字下划线
    - 长度控制到 3~30（按你库的长度调）
    - 为空就用前缀
    """
    if not nickname:
        base = prefix
    else:
        # 去 emoji：只保留常见字符，其他替换成空
        cleaned = re.sub(r"[^\w\s-]", "", nickname, flags=re.UNICODE)
        # 空白/连字符处理
        cleaned = re.sub(r"\s+", "_", cleaned).strip("_-")
        cleaned = cleaned or prefix
        base = cleaned[:24]  # 保留前 24，给随机后缀留空间

    # username 至少 3 长度
    if len(base) < 3:
        base = (base + "xxx")[:3]
    return base

def random_suffix(n=4) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))
