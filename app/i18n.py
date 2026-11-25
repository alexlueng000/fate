"""Request-local language negotiation; calculation identifiers stay unchanged."""
from contextvars import ContextVar

current_locale: ContextVar[str] = ContextVar("current_locale", default="zh-CN")


def output_language_rule() -> str:
    """Constrain prose only; never translate machine-readable protocols."""
    if current_locale.get() != "zh-TW":
        return ""
    return (
        "\n\n【本次回覆語言】\n"
        "本次所有面向使用者的解讀、標題、開場白與建議問題，請使用台灣繁體中文。"
        "即使歷史對話、使用者問題或知識庫為簡體中文，仍以台灣繁體中文回覆。"
        "採用自然的台灣用語，例如資訊、紀錄、帳號；保留命理術語的原意。"
        "此要求僅影響呈現語言，不改變命盤、日期、數字、計算結果或引用事實。"
        "JSON key、枚舉、協定標記及程式識別字必須保持原樣。"
    )


def resolve_locale(header: str = "") -> str:
    candidates = []
    for position, part in enumerate(header.split(",")):
        pieces = part.strip().split(";")
        quality = 1.0
        try:
            for parameter in pieces[1:]:
                if parameter.strip().startswith("q="):
                    quality = float(parameter.strip()[2:])
        except ValueError:
            continue
        if not 0 < quality <= 1:
            continue
        candidates.append((-quality, position, pieces[0].lower()))
    for _, _, tag in sorted(candidates):
        if tag in {"zh-tw", "zh-hant", "zh-hant-tw"}:
            return "zh-TW"
        if tag in {"zh-cn", "zh", "zh-hans", "zh-hans-cn"}:
            return "zh-CN"
    return "zh-CN"


class LocaleMiddleware:
    """Keep context alive for the entire ASGI response, including SSE."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        locale = resolve_locale(headers.get(b"accept-language", b"").decode("latin1"))
        token = current_locale.set(locale)
        try:
            await self.app(scope, receive, send)
        finally:
            current_locale.reset(token)


def payments_unavailable() -> str:
    return ("此地區暫未開放付款。" if current_locale.get() == "zh-TW"
            else "当前地区暂未开放支付。")


def auth_message(message: str) -> str:
    if current_locale.get() != 'zh-TW':
        return message
    return {
        '该邮箱已注册': '此電子郵件地址已註冊',
        '邮箱或密码错误': '電子郵件或密碼錯誤',
        '账户不可用': '此帳戶目前無法使用',
    }.get(message, message)
