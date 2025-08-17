import json, hashlib
from typing import Tuple
# 这里只做示例：真实排盘请替换为你的算法
def compute_bazi_demo(birth_ts: int, calendar: str, city: str | None, lat: float | None, lng: float | None) -> Tuple[dict, list, list]:
    table = {
        "tiangan": ["甲","乙","丙","丁"],
        "dizhi": ["子","丑","寅","卯"],
        "changsheng": ["帝旺","衰","病","死"]
    }
    dayun = [
        {"ganzhi": "乙丑", "age": "10岁"},
        {"ganzhi": "丙寅", "age": "20岁"},
        {"ganzhi": "丁卯", "age": "30岁"},
        {"ganzhi": "戊辰", "age": "40岁"},
        {"ganzhi": "己巳", "age": "50岁"},
    ]
    wuxing = [
        {"name":"金","percent":20,"cls":"wx-gold"},
        {"name":"木","percent":15,"cls":"wx-wood"},
        {"name":"水","percent":30,"cls":"wx-water"},
        {"name":"火","percent":20,"cls":"wx-fire"},
        {"name":"土","percent":15,"cls":"wx-earth"},
    ]
    return table, dayun, wuxing

def bazi_fingerprint(birth_ts: int, calendar: str, city: str | None, lat: float | None, lng: float | None) -> str:
    raw = json.dumps({"birth_ts": birth_ts, "calendar": calendar, "city": city, "lat": lat, "lng": lng}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
