# utils/username.py
import re
import random
import string

def slugify_username(nickname: str | None, prefix: str = "wx") -> str:
    """
    把昵称变成 username 基底：
    - 去掉 emoji / 非字母数字下划线
    - 长度控制到 3~30（按你库的长度调）
    - 始终添加随机后缀确保唯一性
    """
    if not nickname:
        # 空昵称：使用前缀 + 随机后缀
        return f"{prefix}_{random_suffix(8)}"
    else:
        # 去 emoji：只保留常见字符，其他替换成空
        cleaned = re.sub(r"[^\w\s-]", "", nickname, flags=re.UNICODE)
        # 空白/连字符处理
        cleaned = re.sub(r"\s+", "_", cleaned).strip("_-")
        cleaned = cleaned or prefix
        base = cleaned[:20]  # 保留前 20，给随机后缀留空间

        # username 至少 3 长度
        if len(base) < 3:
            base = (base + "xxx")[:3]

        # 始终添加随机后缀确保唯一性
        return f"{base}_{random_suffix(6)}"

def random_suffix(n=4) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))
