"""天气获取与图标绘制（xfabe 天气接口，自动 IP 定位）。

天气图标用程序化点阵绘制（含太阳/云/雨/雪/雷/雾等）。
"""

# 天气图标：18x18 点阵，字符含义同 bigfont.py 的颜色键
# '.'=透明，W/B/G/Y/O/R/L=颜色

# 太阳
SUN = [
    "..................",
    "....Y........Y....",
    ".....Y......Y.....",
    "..................",
    "Y....YYYYYYYY....Y",
    ".Y..YYOOOOOOYY..Y.",
    "...YYOOOOOOOOYY...",
    "..YOOOOOOOOOOOOY..",
    "..YOOOOOOOOOOOOY..",
    "..YOOOOOOOOOOOOY..",
    "...YYOOOOOOOOYY...",
    ".Y..YYOOOOOOYY..Y.",
    "Y....YYYYYYYY....Y",
    "..................",
    ".....Y......Y.....",
    "....Y........Y....",
    "..................",
    "..................",
]

# 云
CLOUD = [
    "..................",
    "..................",
    ".....WWWWWWW......",
    "....WWWWWWWWWW....",
    "...WWWWWWWWWWWW...",
    "..WWWWWWWWWWWWWW..",
    ".WWWWWWWWWWWWWWWW.",
    "WWWWWWWWWWWWWWWWWW",
    "WWWWWWWWWWWWWWWWWW",
    ".WWWWWWWWWWWWWWWW.",
    "..WWWWWWWWWWWWWW..",
    "..................",
    "..................",
    "..................",
    "..................",
    "..................",
    "..................",
    "..................",
]

# 太阳 + 云（多云）
SUN_CLOUD = [
    "..................",
    "....YYY.....W.....",
    "...YYOOYY..WWW....",
    "..YOOOOOOYWWWWW...",
    "..YOOOOOOYWWWWWWW.",
    "...YYOOYYWWWWWWWWW",
    "....YYY.WWWWWWWWWW",
    ".....WWWWWWWWWWWWW",
    "....WWWWWWWWWWWWWW",
    "...WWWWWWWWWWWWWWW",
    "..WWWWWWWWWWWWWWWW",
    ".WWWWWWWWWWWWWWWWW",
    "WWWWWWWWWWWWWWWWWW",
    ".WWWWWWWWWWWWWWWW.",
    "..................",
    "..................",
    "..................",
    "..................",
]

# 雨（云 + 雨滴）
RAIN = [
    "..................",
    ".....WWWWWWW......",
    "....WWWWWWWWWW....",
    "...WWWWWWWWWWWW...",
    "..WWWWWWWWWWWWWW..",
    ".WWWWWWWWWWWWWWWW.",
    "WWWWWWWWWWWWWWWWWW",
    "WWWWWWWWWWWWWWWWWW",
    ".WWWWWWWWWWWWWWWW.",
    "..B....B....B....",
    "...B....B....B...",
    "....B....B....B..",
    "...B....B....B...",
    "....B....B....B..",
    ".....B....B....B.",
    "....B....B....B..",
    "..................",
    "..................",
]

# 雪
SNOW = [
    "..................",
    ".....WWWWWWW......",
    "....WWWWWWWWWW....",
    "...WWWWWWWWWWWW...",
    "..WWWWWWWWWWWWWW..",
    ".WWWWWWWWWWWWWWWW.",
    "WWWWWWWWWWWWWWWWWW",
    "WWWWWWWWWWWWWWWWWW",
    ".WWWWWWWWWWWWWWWW.",
    "..................",
    "...W..W..W..W..W..",
    "....W.W..W.W..W...",
    ".W..W.W..W.W..W.W.",
    "....W.W..W.W..W...",
    "...W..W..W..W..W..",
    "..................",
    "..................",
    "..................",
]

# 雷雨
THUNDER = [
    "..................",
    ".....GGGGGGG......",
    "....GGGGGGGGGG....",
    "...GGGGGGGGGGGG...",
    "..GGGGGGGGGGGGGG..",
    ".GGGGGGGGGGGGGGGG.",
    "GGGGGGGGGGGGGGGGGG",
    "GGGGGGGGGGGGGGGGGG",
    ".GGGGGGGGGGGGGGGG.",
    "...B....B....Y...",
    "....B....B..YY...",
    ".....B....YYY....",
    "......B..YY......",
    "........YYB......",
    ".......YB........",
    "......YB.........",
    "..................",
    "..................",
]

# 雾
FOG = [
    "..................",
    "..................",
    "..................",
    "..WWWWWWWWWWWWWW..",
    ".WWWWWWWWWWWWWWWW.",
    "..WWWWWWWWWWWWWW..",
    "..................",
    "...WWWWWWWWWWWWW..",
    "..WWWWWWWWWWWWWWW.",
    "...WWWWWWWWWWWWW..",
    "..................",
    "..WWWWWWWWWWWWWW..",
    ".WWWWWWWWWWWWWWWW.",
    "..WWWWWWWWWWWWWW..",
    "..................",
    "..................",
    "..................",
    "..................",
]

ICON_COLORS = {
    'W': 0xFFFF,  # 白
    'Y': 0xFFE0,  # 黄
    'O': 0xFD20,  # 橙
    'B': 0x4A1F,  # 蓝(水)
    'G': 0x7BEF,  # 灰(雷云)
    'L': 0xFFE0,  # 闪电黄
}


def _draw_bitmap(disp, bitmap, x, y):
    for row, line in enumerate(bitmap):
        for col, ch in enumerate(line):
            if ch == '.' or ch == ' ':
                continue
            color = ICON_COLORS.get(ch)
            if color is not None:
                disp.pixel(x + col, y + row, color)


# ---- 状况关键词 -> (图标, 中文) 映射 ----
# 顺序敏感：越靠前越优先（雷雨包含雨，必须先判）。
# 中文标签覆盖 16px GB2312 字库常用字，精简到 2~4 字适合小屏。
_COND_RULES = [
    (["thunder", "storm", "雷"],   THUNDER,   "雷雨"),
    (["snow", "ice", "sleet", "blizzard", "雪"], SNOW, "雪"),
    (["heavy rain", "torrential", "downpour", "pouring", "大雨"], RAIN, "大雨"),
    (["rain", "drizzle", "shower", "雨"], RAIN, "雨"),
    (["fog", "mist", "雾"],        FOG,       "雾"),
    (["haze", "smoke", "dust", "sand", "霾", "沙", "尘"], FOG, "雾霾"),
    (["overcast", "阴"],           FOG,       "阴"),
    (["partly", "partially", " partly"], SUN_CLOUD, "多云"),
    (["cloud", "cloudy", "云"],    CLOUD,     "多云"),
    (["clear", "sunny", "晴"],     SUN,       "晴"),
]


def pick_icon(condition):
    """根据 wttr.in 的英文状况描述选图标。"""
    c = condition.lower()
    for _keys, icon, _cn in _COND_RULES:
        if any(k in c for k in _keys):
            return icon
    return SUN  # 默认/晴


def condition_cn(condition):
    """把 wttr.in 英文状况翻译成精简中文（小屏友好）。

    匹配不到则返回 None，由调用方决定回退（显示英文原文）。
    """
    c = condition.lower()
    for _keys, _icon, cn in _COND_RULES:
        if any(k in c for k in _keys):
            return cn
    return None


def _safe_get(url, timeout=10):
    """带超时的 GET，返回文本或 None。兼容 urequests/requests。"""
    try:
        import urequests as req
    except ImportError:
        import requests as req
    try:
        resp = req.get(url, timeout=timeout)
        text = resp.text
        resp.close()
        return text
    except Exception as e:
        print("weather get fail:", e)
        return None


def _loads_json(text):
    try:
        import ujson as json
    except ImportError:
        import json
    return json.loads(text)


def fetch(city=""):
    """获取天气。

    返回 dict: {temp, cond, humidity, wind, high, low, city, raw} 或 None。
    xfabe 接口里 weather[0].temp 是中文天气现象，high/low 才是温度。
    city 参数保留为兼容旧调用，目前接口按 IP 自动定位。
    """
    text = _safe_get("https://node.api.xfabe.com/api/weather/get", timeout=8)
    if not text:
        return None
    try:
        obj = _loads_json(text)
        if obj.get("code") != 200:
            return None
        data = obj.get("data") or {}
        weather = data.get("weather") or []
        if not weather:
            return None
        item = weather[0]
        cond = (item.get("temp") or "").strip()
        high = (item.get("high") or "").strip()
        low = (item.get("low") or "").strip()
        humidity = (item.get("humidity") or "").strip()
        wind_scale = str(item.get("wind_scale") or "").strip()
        wind = (wind_scale + "级") if wind_scale else ""
        return {
            "temp": high,
            "cond": cond,
            "humidity": humidity,
            "wind": wind,
            "high": high,
            "low": low,
            "city": data.get("city") or "",
            "raw": text,
        }
    except Exception as e:
        print("weather json fail:", e)
        return None


def draw_icon_for(disp, condition, x, y):
    """根据状况画对应图标。"""
    icon = pick_icon(condition)
    _draw_bitmap(disp, icon, x, y)
