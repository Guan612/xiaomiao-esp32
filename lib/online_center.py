"""在线大全：网易云热评 + UAPI 热榜聚合。"""

UAPI_HOTBOARD = "https://uapis.cn/api/v1/misc/hotboard?type="
NETEASE_COMMENT = "https://yunapi.cn/api/sjwyyrp"

SERVICES = (
    {"title": "网易云热评", "kind": "text", "url": NETEASE_COMMENT},
    {"title": "微博热榜", "kind": "hotboard", "type": "weibo"},
    {"title": "知乎热榜", "kind": "hotboard", "type": "zhihu"},
    {"title": "B站热榜", "kind": "hotboard", "type": "bilibili"},
    {"title": "抖音热榜", "kind": "hotboard", "type": "douyin"},
    {"title": "百度热榜", "kind": "hotboard", "type": "baidu"},
    {"title": "掘金热榜", "kind": "hotboard", "type": "juejin"},
    {"title": "V2EX热榜", "kind": "hotboard", "type": "v2ex"},
)


def _safe_get(url, timeout=10):
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
        print("online get fail:", e)
        return None


def _clean_text(text):
    if not text:
        return ""
    text = text.strip()
    for old, new in (
        ("\r\n", "\n"),
        ("\r", "\n"),
        ("\\n", "\n"),
        ("&quot;", '"'),
        ("&#34;", '"'),
        ("&amp;", "&"),
    ):
        text = text.replace(old, new)
    while "\n\n" in text:
        text = text.replace("\n\n", "\n")
    return text.strip()


def _pick_json_text(obj):
    if isinstance(obj, str):
        return obj
    if isinstance(obj, list):
        for item in obj:
            text = _pick_json_text(item)
            if text:
                return text
        return ""
    if not isinstance(obj, dict):
        return ""
    for key in ("content", "comment", "text", "hitokoto", "data", "msg", "message"):
        val = obj.get(key)
        if isinstance(val, str) and val.strip():
            return val
        text = _pick_json_text(val)
        if text:
            return text
    return ""


def _loads(text):
    try:
        import ujson as json
    except ImportError:
        import json
    return json.loads(text)


def _parse_text_api(text):
    text = _clean_text(text)
    if not text:
        return []
    if text[0] in ("{", "["):
        try:
            picked = _pick_json_text(_loads(text))
            if picked:
                return [_clean_text(picked)]
        except Exception as e:
            print("online text json parse fail:", e)
    return [text]


def _parse_hotboard(text):
    if not text:
        return []
    try:
        data = _loads(text)
    except Exception as e:
        print("hotboard json parse fail:", e)
        return []
    rows = data.get("list") or data.get("data") or data.get("results") or []
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = row.get("title") or row.get("name") or row.get("keyword") or ""
        if title:
            index = row.get("index") or row.get("rank") or (len(out) + 1)
            hot = row.get("hot_value") or row.get("hot") or row.get("views") or ""
            prefix = "%s. " % index
            suffix = ("  " + str(hot)) if hot else ""
            out.append(prefix + str(title) + suffix)
        if len(out) >= 20:
            break
    return out


def fetch(service):
    """返回字符串列表；第一项可是一段文本，也可是一组热榜条目。"""
    if service.get("kind") == "hotboard":
        text = _safe_get(UAPI_HOTBOARD + service.get("type", "weibo"))
        return _parse_hotboard(text)
    return _parse_text_api(_safe_get(service.get("url", NETEASE_COMMENT)))
