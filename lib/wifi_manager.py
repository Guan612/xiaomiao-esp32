"""WiFi 凭证管理 + 连接调度。

凭据存在板子 flash 的 /wifi.json：
  {"networks": [{"ssid": "...", "password": "..."}]}  # 多 WiFi 格式
由 captive_portal.py 配网页写入，本模块负责读取并尝试连接。

入口：ensure_connected(disp) —— 读凭据→连 STA→失败/无则按需进配网。
返回 (wlan, ip)；进配网后不会返回（配网成功会重启）。
"""
import time
import json
import network

import captive_portal as portal

WIFI_FILE = portal.WIFI_FILE  # "/wifi.json"


def load_creds():
    """读 /wifi.json，返回 [(ssid, password), ...] 或空列表。"""
    try:
        with open(WIFI_FILE, "r") as f:
            data = json.load(f)
        creds = []
        seen = set()
        for item in data.get("networks", []):
            ssid = item.get("ssid", "").strip()
            password = item.get("password", "")
            if ssid and ssid not in seen:
                creds.append((ssid, password))
                seen.add(ssid)

        return creds
    except (OSError, ValueError):
        return []


def _save_creds(creds):
    networks = []
    seen = set()
    for ssid, password in creds:
        ssid = ssid.strip()
        if ssid and ssid not in seen:
            networks.append({"ssid": ssid, "password": password})
            seen.add(ssid)
    with open(WIFI_FILE, "w") as f:
        json.dump({"networks": networks}, f)


def _remember_success(creds, ok_ssid):
    """把本次连上的 WiFi 放到最前，下次优先试。"""
    if not ok_ssid or not creds or creds[0][0] == ok_ssid:
        return
    ordered = []
    for ssid, password in creds:
        if ssid == ok_ssid:
            ordered.insert(0, (ssid, password))
        else:
            ordered.append((ssid, password))
    try:
        _save_creds(ordered)
    except OSError as e:
        print("[wifi] save preferred failed:", e)


def _ssid_text(raw):
    if isinstance(raw, bytes):
        try:
            return raw.decode("utf-8")
        except Exception:
            return raw.decode("latin-1")
    return raw


def _prioritize_visible_creds(creds):
    """扫描附近热点，优先尝试当前能看到的已保存 WiFi。"""
    if not creds:
        return creds
    try:
        wlan = network.WLAN(network.STA_IF)
        wlan.active(True)
        found = {}
        for ap in wlan.scan():
            ssid = _ssid_text(ap[0])
            rssi = ap[3] if len(ap) > 3 else -999
            if ssid not in found or rssi > found[ssid]:
                found[ssid] = rssi
    except Exception as e:
        print("[wifi] scan failed:", e)
        return creds

    visible = []
    hidden_or_absent = []
    for item in creds:
        ssid = item[0]
        if ssid in found:
            visible.append((found[ssid], item))
        else:
            hidden_or_absent.append(item)
    if not visible:
        return creds
    visible.sort(reverse=True)
    ordered = [item for _rssi, item in visible] + hidden_or_absent
    print("[wifi] visible saved networks:", len(visible))
    return ordered


def connect_sta(ssid, password, timeout_ms=25000, retries=2):
    """连 STA，返回 (wlan, ip) 或 (None, None)。

    沿用 astronaut_watch.py 原 connect_wifi 的连接+超时等待模式。
    """
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    for attempt in range(1, retries + 1):
        if wlan.isconnected():
            break
        try:
            wlan.disconnect()
            time.sleep(0.3)
        except Exception:
            pass
        print("[wifi] connecting to", ssid)
        if retries > 1:
            print("[wifi] attempt", attempt, "of", retries)
        wlan.connect(ssid, password)
        deadline = time.ticks_add(time.ticks_ms(), timeout_ms)
        while time.ticks_diff(deadline, time.ticks_ms()) > 0:
            if wlan.isconnected():
                break
            try:
                # Negative statuses are terminal on ESP32: no AP, bad password, etc.
                if wlan.status() < 0:
                    break
            except Exception:
                pass
            time.sleep(0.3)
        if wlan.isconnected():
            break
        try:
            print("[wifi] status:", wlan.status())
        except Exception:
            pass
    if wlan.isconnected():
        ip = wlan.ifconfig()[0]
        print("[wifi] ok, ip:", ip)
        return wlan, ip
    print("[wifi] FAILED")
    return None, None


def run_setup(disp=None):
    """进入 AP 配网。正常配网成功会重启，不会返回。"""
    portal.run(disp)
    return None, None


def ensure_connected(disp=None, setup_on_fail=True, timeout_ms=25000,
                     retries=2, scan=True, max_creds=0):
    """顶层入口：读凭据→连→失败/无则可选进配网。返回 (wlan, ip)。

    setup_on_fail=False 用于离线优先的应用：没有网络时尽快返回，让本地工具
    继续可用，而不是卡在 WiFi 配网或长时间重试里。max_creds>0 时只快速
    尝试前几个已保存网络，避免保存网络很多时逐个超时。
    """
    creds = load_creds()
    if creds:
        if scan:
            creds = _prioritize_visible_creds(creds)
        if max_creds > 0:
            creds = creds[:max_creds]
        total = len(creds)
        for idx, (ssid, password) in enumerate(creds, 1):
            print("[wifi] stored network", idx, "of", total)
            wlan, ip = connect_sta(ssid, password, timeout_ms=timeout_ms,
                                   retries=retries)
            if wlan:
                _remember_success(creds, ssid)
                return wlan, ip
        print("[wifi] all stored creds failed")
    else:
        print("[wifi] no stored creds")
    if setup_on_fail:
        print("[wifi] entering setup")
        return run_setup(disp)
    print("[wifi] offline mode")
    return None, None
