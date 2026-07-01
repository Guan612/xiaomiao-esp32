r"""WiFi 太空人手表（含天气 + AP 配网 + 中文字库）。

功能：
  1. AP 配网：无 WiFi 凭据(或连不上)时，板子开热点，手机连上后自动弹配网页
     选 WiFi、输密码，存盘重启后自动连接。详情见 lib/captive_portal.py。
  2. NTP 对时（aliyun, UTC+8）
  3. 天气手动刷新（避免网络请求阻塞启动）
  4. 屏幕显示：太空人 + 大号时间 + 日期 + 天气(图标+温度+湿度+状况)

中文字库：用 font/noto_sans_sc_16px_gb2312.v3.bmf（GB2312 常用字符），
经 lib/easydisplay.py 渲染。时间数字仍用 bigfont 像素大字体（更醒目）。

首次使用：开机后手机连 "Xueersi-Setup" 热点 → 弹出配网页 → 选 WiFi → 输密码。

部署 (Windows cmd 用反斜杠，PowerShell/sh 用正斜杠)：
  uv run python scripts/flash.py upload apps\wifi_config.py
  uv run python scripts/flash.py upload apps\astronaut_watch.py :/main.py
  uv run python scripts/flash.py upload lib\st7735_buf.py
  uv run python scripts/flash.py upload lib\bigfont.py
  uv run python scripts/flash.py upload lib\easydisplay.py
  uv run python scripts/flash.py upload lib\watch_ui.py
  uv run python scripts/flash.py upload lib\keynav.py
  uv run python scripts/flash.py upload lib\weather.py
  uv run python scripts/flash.py upload lib\online_center.py
  uv run python scripts/flash.py upload lib\wifi_manager.py
  uv run python scripts/flash.py upload lib\captive_portal.py
  # 中文字库（务必传到板子 /font/ 目录）：
  uv run python scripts/flash.py upload font\noto_sans_sc_16px_gb2312.v3.bmf :/font/noto_sans_sc_16px_gb2312.v3.bmf

复位即运行。
"""
import sys
import time
import gc
import random

sys.path.append("/lib")

from machine import Pin, SPI, RTC  # noqa: E402
import machine  # noqa: E402  (for machine.reset)
import st7735_buf as st  # noqa: E402
import astro_icon  # noqa: E402
import easydisplay as ed  # noqa: E402
import weather as wx  # noqa: E402
import wifi_manager as wmgr  # noqa: E402
import captive_portal as portal  # noqa: E402
import webui as webui_mod  # noqa: E402
import local_sensor  # noqa: E402
import online_center  # noqa: E402
from keynav import KeyNav  # noqa: E402
import watch_ui as ui  # noqa: E402

import wifi_config as cfg  # noqa: E402

# ---- 中文字库路径 ----
FONT_FILE = "/font/noto_sans_sc_16px_gb2312.v3.bmf"

WHITE = 0xFFFF
YELLOW = 0xFFE0
RED = 0xF800

PAGES = ("setup", "clock", "online", "weather", "dice")
INPUT_POLL_MS = 35


def init_display():
    spi = SPI(2, baudrate=20000000, polarity=0, phase=0,
              sck=Pin(18), mosi=Pin(23))
    disp = st.ST7735(width=160, height=128, spi=spi, cs=5, dc=4, res=19,
                     rotate=1, bl=None, invert=False, rgb=True)
    return disp


def init_easydisp(disp):
    """加载中文字库，返回 EasyDisplay；字库缺失则返回 None（回退纯英文）。"""
    try:
        return ed.EasyDisplay(disp, "RGB565", font=FONT_FILE)
    except Exception as e:
        print("字体加载失败，回退英文:", e)
        return None


def enter_flash_mode(disp, easydisp, web=None):
    """进入 USB 上传/刷写待机：停网络和 HTTP，只保留可打断的轻循环。"""
    print("[flash] entering USB flash/upload mode")
    if web:
        try:
            web.close()
        except Exception as e:
            print("[flash] web close fail:", e)
    try:
        import network
        for iface in (network.WLAN(network.STA_IF), network.WLAN(network.AP_IF)):
            try:
                iface.active(False)
            except Exception:
                pass
    except Exception as e:
        print("[flash] network off fail:", e)
    gc.collect()
    ui.show_flash_mode_screen(disp, easydisp)
    print("[flash] ready: run `uv run python scripts/flash.py upload <local> [:/remote]`")
    while True:
        time.sleep(1)   # Ctrl-C 能干净打断，电脑端随后进入 raw REPL


def sync_ntp():
    """NTP 对时，返回是否成功。"""
    try:
        import ntptime
        ntptime.host = cfg.NTP_HOST
        ntptime.timeout = 3
        ntptime.settime()
        t = time.time() + cfg.TIMEZONE[0]
        tm = time.localtime(t)
        try:
            rtc = RTC()
            rtc.datetime((tm[0], tm[1], tm[2], tm[6] + 1,
                          tm[3], tm[4], tm[5], 0))
        except Exception:
            pass
        print("ntp synced")
        return True
    except Exception as e:
        print("ntp FAILED:", e)
        return False


def next_page(page, delta, pages=PAGES):
    idx = pages.index(page)
    return pages[(idx + delta) % len(pages)]


def roll_dice():
    sensor = local_sensor.entropy_sample()
    seed = sensor["seed"] ^ time.ticks_us() ^ (time.ticks_ms() << 3) ^ (time.time() << 2)
    random.seed(seed)
    return {"value": random.getrandbits(8) % 6 + 1}


def wifi_setup_requested(disp, easydisp, window_ms=1800):
    """启动时短暂监听 A 键；按下才进入会阻塞的 AP 配网。"""
    ui.show_status(disp, easydisp, "A:WiFi setup", YELLOW)
    try:
        a_key = Pin(34, Pin.IN, Pin.PULL_UP)
        deadline = time.ticks_add(time.ticks_ms(), window_ms)
        while time.ticks_diff(deadline, time.ticks_ms()) > 0:
            if a_key.value() == 0:
                return True
            time.sleep_ms(40)
    except Exception as e:
        print("wifi setup key check fail:", e)
    return False


def main():
    disp = init_display()
    easydisp = init_easydisp(disp)
    ui.show_status(disp, easydisp, "Booting...", WHITE)

    # 离线优先：本地工具（如色子）不能因为无网络/未配网而被启动流程卡住。
    # 如需配网，复位后在启动提示期间按 A 进入 AP 配网（配网成功后会重启）。
    if wifi_setup_requested(disp, easydisp):
        ui.show_status(disp, easydisp, "WiFi Setup...", YELLOW)
        if wmgr.run_setup(disp) == "flash":
            enter_flash_mode(disp, easydisp)
    ui.show_status(disp, easydisp, "Connecting WiFi...", YELLOW)
    wlan, ip = wmgr.ensure_connected(
        disp,
        setup_on_fail=False,
        timeout_ms=30000,
        retries=3,
        scan=True,
        max_creds=3,
    )
    if wlan:
        ui.show_status(disp, easydisp, "Syncing time...", YELLOW)
        sync_ntp()
    else:
        if wmgr.load_creds():
            ui.show_status(disp, easydisp, "WiFi retrying...", RED)
        else:
            ui.show_status(disp, easydisp, "Offline AP starting", RED)

    # 天气 HTTPS 在当前固件/网络上不稳定；不在启动阶段阻塞主界面。
    weather_data = None

    last_ntp = time.time()
    last_weather = time.time()
    last_sensor = time.ticks_add(time.ticks_ms(), -2000)
    next_wifi_retry = time.ticks_add(time.ticks_ms(), 30000)
    local_temp = ""
    page = "clock" if wlan else "setup"
    pages = ("clock", "online", "weather", "dice") if wlan else PAGES
    online_mode = "menu"
    online_selected = 0
    online_lines = []
    online_error = ""
    online_scroll = 0
    weather_error = ""
    online_dirty = True
    weather_dirty = True
    setup_dirty = True
    dice_dirty = True
    dice = {"value": 1}
    last_page = None
    last_astro_frame = -1

    keys = KeyNav()

    # 在线用 STA 控制台；无 WiFi 凭据时才自动开 AP 配网。
    # 已有凭据但临时连接失败时保持 STA，后台定时重连，避免 AP 模式关闭 STA。
    web = None
    if wlan:
        try:
            ssid = wlan.config("essid")
        except Exception:
            ssid = ""
        web = webui_mod.WebUI(disp, easydisp)
        web.set_state(ip=ip, ssid=ssid)
    elif not wmgr.load_creds():
        try:
            web = portal.CaptivePortalUI()
        except Exception as e:
            print("offline portal start fail:", e)
            web = None

    while True:
        key_hits = keys.poll()
        if key_hits:
            if "b_long" in key_hits:
                page = "clock"
                last_page = None
                online_mode = "menu"
                online_dirty = True
                weather_dirty = True
                setup_dirty = True
                dice_dirty = True
                continue
            if "down" in key_hits and page == "online":
                if online_mode == "menu":
                    online_selected = (online_selected + 1) % len(online_center.SERVICES)
                    online_dirty = True
                elif online_lines:
                    wrapped = []
                    for item in online_lines:
                        wrapped.extend(ui.wrap_text(item, max_units=18))
                    max_scroll = max(0, len(wrapped) - 5)
                    if online_scroll < max_scroll:
                        online_scroll += 1
                        online_dirty = True
            elif "up" in key_hits and page == "online":
                if online_mode == "menu":
                    online_selected = (online_selected - 1) % len(online_center.SERVICES)
                    online_dirty = True
                elif online_lines and online_scroll > 0:
                    online_scroll -= 1
                    online_dirty = True
            if "right" in key_hits:
                page = next_page(page, 1, pages)
                last_page = None
                online_dirty = True
                weather_dirty = True
                setup_dirty = True
                dice_dirty = True
            if "left" in key_hits:
                page = next_page(page, -1, pages)
                last_page = None
                online_dirty = True
                weather_dirty = True
                setup_dirty = True
                dice_dirty = True
            if "b" in key_hits:
                if page == "online" and online_mode == "detail":
                    online_mode = "menu"
                    online_dirty = True
                else:
                    page = "clock"
                    last_page = None
            if page == "online" and "a" in key_hits:
                if online_mode == "menu":
                    online_mode = "detail"
                    online_lines = []
                    online_error = ""
                    online_scroll = 0
                service = online_center.SERVICES[online_selected]
                if wlan:
                    ui.draw_online_detail(
                        disp, easydisp, service.get("title", ""), online_lines,
                        loading=True,
                    )
                    gc.collect()
                    try:
                        online_lines = online_center.fetch(service)
                        online_error = "" if online_lines else "获取失败"
                        online_scroll = 0
                    except Exception as e:
                        print("online refresh fail:", e)
                        online_error = "获取失败"
                    online_dirty = True
                else:
                    online_error = "离线不可用"
                    online_dirty = True
            if page == "weather" and "a" in key_hits:
                if wlan:
                    ui.draw_weather_page(disp, easydisp, ip, True, weather_data,
                                      loading=True)
                    gc.collect()
                    try:
                        new_w = wx.fetch(cfg.WEATHER_CITY)
                        if new_w:
                            weather_data = new_w
                            weather_error = ""
                            last_weather = time.time()
                        else:
                            weather_error = "天气获取失败"
                    except Exception as e:
                        print("weather manual refresh fail:", e)
                        weather_error = "天气获取失败"
                    weather_dirty = True
                else:
                    weather_error = "离线不可用"
                    weather_dirty = True
            if page == "dice" and "a" in key_hits:
                try:
                    for i in range(5):
                        ui.draw_dice_page(
                            disp, easydisp, (time.ticks_ms() + i) % 6 + 1,
                            rolling=True,
                        )
                        time.sleep_ms(55)
                    dice = roll_dice()
                except Exception as e:
                    print("dice roll fail:", e)
                    dice = {"value": random.getrandbits(8) % 6 + 1}
                dice_dirty = True

        now = time.localtime()
        if time.ticks_diff(time.ticks_ms(), last_sensor) >= 2000:
            try:
                local_temp = local_sensor.temperature_label()
            except Exception as e:
                print("local temp fail:", e)
                local_temp = ""
            last_sensor = time.ticks_ms()
        astro_frame = time.ticks_ms() // astro_icon.FRAME_MS
        if page == "setup" and setup_dirty:
            ui.draw_setup_page(disp, easydisp, portal.AP_SSID, portal.AP_IP)
            setup_dirty = False
        elif page == "clock" and (last_page != page or astro_frame != last_astro_frame):
            ui.draw_clock(disp, easydisp, now, ip, wlan is not None,
                       weather_data, astro_frame, local_temp)
            last_astro_frame = astro_frame
        elif page == "online" and online_dirty:
            if online_mode == "menu":
                ui.draw_online_menu(
                    disp, easydisp, online_center.SERVICES, online_selected,
                )
            else:
                service = online_center.SERVICES[online_selected]
                ui.draw_online_detail(
                    disp, easydisp, service.get("title", ""), online_lines,
                    err=online_error, scroll=online_scroll,
                )
            online_dirty = False
        elif page == "weather" and weather_dirty:
            ui.draw_weather_page(disp, easydisp, ip, wlan is not None, weather_data,
                              err=weather_error)
            weather_dirty = False
        elif page == "dice" and dice_dirty:
            ui.draw_dice_page(disp, easydisp, dice.get("value", 1))
            dice_dirty = False
        last_page = page
        gc.collect()

        if not wlan and wmgr.load_creds() and time.ticks_diff(
                time.ticks_ms(), next_wifi_retry) >= 0:
            print("[wifi] retry saved networks")
            wlan, ip = wmgr.ensure_connected(
                disp,
                setup_on_fail=False,
                timeout_ms=30000,
                retries=3,
                scan=True,
                max_creds=3,
            )
            next_wifi_retry = time.ticks_add(time.ticks_ms(), 60000)
            if wlan:
                print("[wifi] recovered:", ip)
                pages = ("clock", "online", "weather", "dice")
                page = "clock"
                last_page = None
                online_dirty = True
                weather_dirty = True
                setup_dirty = True
                dice_dirty = True
                try:
                    ssid = wlan.config("essid")
                except Exception:
                    ssid = ""
                web = webui_mod.WebUI(disp, easydisp)
                web.set_state(ip=ip, ssid=ssid)
                try:
                    sync_ntp()
                    last_ntp = time.time()
                except Exception:
                    pass

        # 定时 NTP（每小时）
        if wlan and (time.time() - last_ntp > 3600):
            try:
                sync_ntp()
                last_ntp = time.time()
            except Exception:
                pass

        # 定时刷新天气
        if wlan and weather_data and (time.time() - last_weather > cfg.WEATHER_INTERVAL):
            try:
                new_w = wx.fetch(cfg.WEATHER_CITY)
                if new_w:
                    weather_data = new_w
                last_weather = time.time()
            except Exception as e:
                print("weather refresh fail:", e)

        # 同步面板天气状态
        if web and weather_data:
            cond = wx.condition_cn(weather_data["cond"]) or weather_data["cond"][:12]
            web.set_state(weather="%s %s" % (weather_data["temp"], cond))

        # 按键用更短轮询间隔；太空人动画仍按 FRAME_MS 节奏刷新。
        if web:
            action = web.poll(INPUT_POLL_MS)
        else:
            time.sleep_ms(INPUT_POLL_MS)
            action = None

        # 动作分发
        if action == "flash":
            print("[webui] entering flash mode")
            enter_flash_mode(disp, easydisp, web)
        if action == "reboot":
            print("[webui] reboot")
            machine.reset()
        if action == "resync":
            print("[webui] resync ntp + weather")
            if wlan:
                if page == "weather":
                    ui.draw_weather_page(disp, easydisp, ip, True, weather_data,
                                      loading=True)
                gc.collect()
                if sync_ntp():
                    last_ntp = time.time()
                try:
                    new_w = wx.fetch(cfg.WEATHER_CITY)
                    if new_w:
                        weather_data = new_w
                        weather_error = ""
                        last_weather = time.time()
                        cond = wx.condition_cn(new_w["cond"]) or new_w["cond"][:12]
                        if web:
                            web.set_state(weather="%s %s" % (new_w["temp"], cond))
                    else:
                        weather_error = "天气获取失败"
                        if web:
                            web.set_state(weather=weather_error)
                except Exception as e:
                    print("webui weather refresh fail:", e)
                    weather_error = "天气获取失败"
                    if web:
                        web.set_state(weather=weather_error)
                weather_dirty = True
                last_page = None
            else:
                weather_error = "离线不可用"
                if web:
                    web.set_state(weather=weather_error)
                weather_dirty = True
        if action == "rewifi":
            print("[webui] clear wifi creds + reboot")
            try:
                import os
                os.remove("/wifi.json")
            except Exception:
                pass
            machine.reset()

if __name__ == "__main__":
    main()
