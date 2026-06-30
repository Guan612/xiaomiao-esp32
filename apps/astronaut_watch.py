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
  uv run python scripts/flash.py upload lib\netease_hot.py
  uv run python scripts/flash.py upload lib\wifi_manager.py
  uv run python scripts/flash.py upload lib\captive_portal.py
  # 中文字库（务必传到板子 /font/ 目录）：
  uv run python scripts/flash.py upload font\noto_sans_sc_16px_gb2312.v3.bmf :/font/noto_sans_sc_16px_gb2312.v3.bmf

复位即运行。
"""
import sys
import time
import gc

sys.path.append("/lib")

from machine import Pin, SPI, RTC  # noqa: E402
import machine  # noqa: E402  (for machine.reset)
import st7735_buf as st  # noqa: E402
import astro_icon  # noqa: E402
import easydisplay as ed  # noqa: E402
import weather as wx  # noqa: E402
import wifi_manager as wmgr  # noqa: E402
import webui as webui_mod  # noqa: E402
import local_sensor  # noqa: E402
import netease_hot  # noqa: E402
from keynav import KeyNav  # noqa: E402
import watch_ui as ui  # noqa: E402

import wifi_config as cfg  # noqa: E402

# ---- 中文字库路径 ----
FONT_FILE = "/font/noto_sans_sc_16px_gb2312.v3.bmf"

WHITE = 0xFFFF
YELLOW = 0xFFE0
RED = 0xF800


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


def main():
    disp = init_display()
    easydisp = init_easydisp(disp)
    ui.show_status(disp, easydisp, "Booting...", WHITE)

    # 连 WiFi：无凭据或连不上时自动进入 AP 配网（配网成功后会重启）
    ui.show_status(disp, easydisp, "Connecting WiFi...", YELLOW)
    wlan, ip = wmgr.ensure_connected(disp)
    if wlan:
        ui.show_status(disp, easydisp, "Syncing time...", YELLOW)
        sync_ntp()
    else:
        ui.show_status(disp, easydisp, "No WiFi - offline", RED)
        time.sleep(1)

    # 天气 HTTPS 在当前固件/网络上不稳定；不在启动阶段阻塞主界面。
    weather_data = None

    last_ntp = time.time()
    last_weather = time.time()
    last_sensor = time.ticks_add(time.ticks_ms(), -2000)
    local_temp = ""
    page = "clock"
    hot_comment = None
    hot_error = ""
    hot_scroll = 0
    weather_error = ""
    hot_dirty = True
    weather_dirty = True

    keys = KeyNav()

    # WebUI 控制面板（仅在线时启动；离线无意义）
    web = None
    if wlan:
        try:
            ssid = wlan.config("essid")
        except Exception:
            ssid = ""
        web = webui_mod.WebUI(disp, easydisp)
        web.set_state(ip=ip, ssid=ssid)

    while True:
        key_hits = keys.poll()
        if key_hits:
            if "down" in key_hits and page == "hot" and hot_comment:
                max_scroll = max(0, len(ui.wrap_text(hot_comment, max_units=18)) - 5)
                if hot_scroll < max_scroll:
                    hot_scroll += 1
                    hot_dirty = True
            elif "up" in key_hits and page == "hot" and hot_comment:
                if hot_scroll > 0:
                    hot_scroll -= 1
                    hot_dirty = True
            if "right" in key_hits:
                if page == "clock":
                    page = "hot"
                    hot_dirty = True
                elif page == "hot":
                    page = "weather"
                    weather_dirty = True
                else:
                    page = "clock"
            if "left" in key_hits:
                if page == "clock":
                    page = "weather"
                    weather_dirty = True
                elif page == "weather":
                    page = "hot"
                    hot_dirty = True
                else:
                    page = "clock"
            if "b" in key_hits:
                page = "clock"
            if page == "hot" and "a" in key_hits:
                if wlan:
                    ui.draw_hot_comment(disp, easydisp, ip, True, hot_comment,
                                     loading=True)
                    gc.collect()
                    try:
                        hot_comment = netease_hot.fetch()
                        hot_error = "" if hot_comment else "热评获取失败"
                        hot_scroll = 0
                    except Exception as e:
                        print("hot refresh fail:", e)
                        hot_error = "热评获取失败"
                    hot_dirty = True
                else:
                    hot_error = "离线不可用"
                    hot_dirty = True
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

        now = time.localtime()
        if time.ticks_diff(time.ticks_ms(), last_sensor) >= 2000:
            try:
                local_temp = local_sensor.temperature_label()
            except Exception as e:
                print("local temp fail:", e)
                local_temp = ""
            last_sensor = time.ticks_ms()
        astro_frame = time.ticks_ms() // astro_icon.FRAME_MS
        if page == "clock":
            ui.draw_clock(disp, easydisp, now, ip, wlan is not None,
                       weather_data, astro_frame, local_temp)
        elif page == "hot" and hot_dirty:
            ui.draw_hot_comment(disp, easydisp, ip, wlan is not None, hot_comment,
                             err=hot_error, scroll=hot_scroll)
            hot_dirty = False
        elif page == "weather" and weather_dirty:
            ui.draw_weather_page(disp, easydisp, ip, wlan is not None, weather_data,
                              err=weather_error)
            weather_dirty = False
        gc.collect()

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

        # 【关键】用 WebUI.poll 替代原 sleep_ms：轮询期间仍可响应 HTTP 请求
        if web:
            action = web.poll(astro_icon.FRAME_MS)
        else:
            time.sleep_ms(astro_icon.FRAME_MS)
            action = None

        # 动作分发
        if action == "flash":
            print("[webui] entering flash mode")
            break  # 跳出循环，进入刷写模式待机
        if action == "reboot":
            print("[webui] reboot")
            machine.reset()
        if action == "resync":
            print("[webui] resync ntp")
            last_ntp = 0       # 触发下一帧立即对时
        if action == "rewifi":
            print("[webui] clear wifi creds + reboot")
            try:
                import os
                os.remove("/wifi.json")
            except Exception:
                pass
            machine.reset()

    # ---- 刷写模式待机：不再碰网络，软 sleep 等 USB 上传 ----
    ui.show_flash_mode_screen(disp, easydisp)
    while True:
        time.sleep(1)   # Ctrl-C 能在此干净打断 → flash.py upload 可靠进 raw REPL


if __name__ == "__main__":
    main()
