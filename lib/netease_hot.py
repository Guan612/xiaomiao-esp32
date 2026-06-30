"""网易云热评获取。

数据源：https://yunapi.cn/api/sjwyyrp
接口可能返回纯文本，也可能返回 JSON；这里做宽松解析，尽量在小内存设备上
拿到一段适合 160x128 屏幕显示的文字。
"""

API_URL = "https://yunapi.cn/api/sjwyyrp"


def _safe_get(url=API_URL, timeout=10):
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
        print("netease hot get fail:", e)
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
    """从常见 API JSON 结构里挑出最像评论正文的字段。"""
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


def parse(text):
    text = _clean_text(text)
    if not text:
        return None
    if text[0] in ("{", "["):
        try:
            import ujson as json
        except ImportError:
            import json
        try:
            picked = _pick_json_text(json.loads(text))
            if picked:
                return _clean_text(picked)
        except Exception as e:
            print("netease hot json parse fail:", e)
    return text


def fetch():
    return parse(_safe_get())
