"""WiFi 凭证管理 + 连接调度。

凭据存在板子 flash 的 /wifi.json：{"ssid": "...", "password": "..."}
由 captive_portal.py 配网页写入，本模块负责读取并尝试连接。

入口：ensure_connected(disp) —— 读凭据→连 STA→失败/无则进配网。
返回 (wlan, ip)；进配网后不会返回（配网成功会重启）。
"""
import time
import json
import network

import captive_portal as portal

WIFI_FILE = portal.WIFI_FILE  # "/wifi.json"


def load_creds():
    """读 /wifi.json，返回 (ssid, password) 或 None（无文件/损坏）。"""
    try:
        with open(WIFI_FILE, "r") as f:
            data = json.load(f)
        ssid = data.get("ssid", "").strip()
        password = data.get("password", "")
        if not ssid:
            return None
        return ssid, password
    except (OSError, ValueError):
        return None


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


def ensure_connected(disp=None):
    """顶层入口：读凭据→连→失败/无则进配网。返回 (wlan, ip)。"""
    creds = load_creds()
    if creds:
        wlan, ip = connect_sta(creds[0], creds[1])
        if wlan:
            return wlan, ip
        # 连不上（密码改了/信号差/不在范围）→ 进配网重配
        print("[wifi] stored creds failed, entering setup")
    else:
        print("[wifi] no stored creds, entering setup")
    # 进配网（内部会阻塞直到配完重启，正常不返回）
    portal.run(disp)
    # 万一 run() 异常返回，返回 None 让上层进离线模式
    return None, None
