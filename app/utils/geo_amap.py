# app/utils/geocode_amap.py
import os, math, time
import requests
from typing import Optional, Tuple

# AMAP_KEY = os.getenv("AMAP_KEY", "")
AMAP_KEY = "412c783e3dd295514ef49bb513102b89"
AMAP_GEOCODE_URL = "https://restapi.amap.com/v3/geocode/geo"
UA = "Fate/1.0"  # 换成你的联系方式

# ---- 小缓存：避免重复外呼 ----
_geo_cache_city: dict[str, tuple[float, float]] = {}  # city -> (wgs_lat, wgs_lng)

def _out_of_china(lat: float, lng: float) -> bool:
    return not (73.66 <= lng <= 135.05 and 3.86 <= lat <= 53.55)

def _transform_lat(x: float, y: float) -> float:
    ret = -100.0 + 2.0*x + 3.0*y + 0.2*y*y + 0.1*x*y + 0.2*math.sqrt(abs(x))
    ret += (20.0*math.sin(6.0*x*math.pi) + 20.0*math.sin(2.0*x*math.pi)) * 2.0/3.0
    ret += (20.0*math.sin(y*math.pi) + 40.0*math.sin(y/3.0*math.pi)) * 2.0/3.0
    ret += (160.0*math.sin(y/12.0*math.pi) + 320.0*math.sin(y*math.pi/30.0)) * 2.0/3.0
    return ret

def _transform_lng(x: float, y: float) -> float:
    ret = 300.0 + x + 2.0*y + 0.1*x*x + 0.1*x*y + 0.1*math.sqrt(abs(x))
    ret += (20.0*math.sin(6.0*x*math.pi) + 20.0*math.sin(2.0*x*math.pi)) * 2.0/3.0
    ret += (20.0*math.sin(x*math.pi) + 40.0*math.sin(x/3.0*math.pi)) * 2.0/3.0
    ret += (150.0*math.sin(x/12.0*math.pi) + 300.0*math.sin(x/30.0*math.pi)) * 2.0/3.0
    return ret

def _gcj02_to_wgs84(gcj_lat: float, gcj_lng: float) -> tuple[float, float]:
    """GCJ-02 近似反算为 WGS-84。"""
    if _out_of_china(gcj_lat, gcj_lng):
        return gcj_lat, gcj_lng
    a = 6378245.0
    ee = 0.00669342162296594323
    dlat = _transform_lat(gcj_lng - 105.0, gcj_lat - 35.0)
    dlng = _transform_lng(gcj_lng - 105.0, gcj_lat - 35.0)
    radlat = gcj_lat / 180.0 * math.pi
    magic = math.sin(radlat)
    magic = 1 - ee * magic * magic
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((a * (1 - ee)) / (magic * sqrtmagic) * math.pi)
    dlng = (dlng * 180.0) / (a / sqrtmagic * math.cos(radlat) * math.pi)
    mg_lat = gcj_lat + dlat
    mg_lng = gcj_lng + dlng
    wgs_lat = gcj_lat * 2 - mg_lat
    wgs_lng = gcj_lng * 2 - mg_lng
    return wgs_lat, wgs_lng

def geocode_city(city: str, retries: int = 2, timeout: float = 5.0) -> dict:
    """
    用高德把城市解析为 WGS-84，经纬度；成功返回:
      {"city": "<入参>", "lat": <float>, "lng": <float>}
    失败返回:
      {"error": "..."}
    """
    if not city:
        return {"error": "城市名不能为空"}

    if city in _geo_cache_city:
        lat, lng = _geo_cache_city[city]
        return {"city": city, "lat": lat, "lng": lng}

    if not AMAP_KEY:
        return {"error": "AMAP_KEY 未设置"}

    params = {"address": city, "key": AMAP_KEY}
    headers = {"User-Agent": UA}

    for i in range(retries + 1):
        try:
            r = requests.get(AMAP_GEOCODE_URL, params=params, headers=headers, timeout=timeout)
            r.raise_for_status()
            data = r.json()
            if data.get("status") != "1":
                info = data.get("info") or "geocode failed"
                return {"error": f"高德返回异常: {info}"}
            geos = data.get("geocodes") or []
            if not geos:
                return {"error": f"找不到城市: {city}"}
            loc = geos[0].get("location")  # "lng,lat"
            if not loc or "," not in loc:
                return {"error": "高德未返回坐标"}
            lng_str, lat_str = loc.split(",", 1)
            gcj_lng = float(lng_str)
            gcj_lat = float(lat_str)
            wgs_lat, wgs_lng = _gcj02_to_wgs84(gcj_lat, gcj_lng)
            _geo_cache_city[city] = (wgs_lat, wgs_lng)
            return {"city": city, "lat": wgs_lat, "lng": wgs_lng}
        except requests.RequestException as e:
            if i == retries:
                return {"error": f"网络异常: {e.__class__.__name__}"}
            time.sleep(1.5 * (i + 1))


if __name__ == "__main__":
    print(geocode_city("广东阳春"))