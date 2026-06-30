r"""WiFi 太空人手表（含天气 + AP 配网 + 中文字库）。

功能：
  1. AP 配网：无 WiFi 凭据(或连不上)时，板子开热点，手机连上后自动弹配网页
     选 WiFi、输密码，存盘重启后自动连接。详情见 lib/captive_portal.py。
  2. NTP 对时（aliyun, UTC+8）
  3. 天气手动刷新（避免网络请求阻塞启动）
  4. 屏幕显示：太空人 + 大号时间 + 日期 + 天气(图标+温度+湿度+状况)

中文字库：用 font/text_lite_16px_2312.v3.bmf（GB2312，3983 字），
经 lib/easydisplay.py 渲染。时间数字仍用 bigfont 像素大字体（更醒目）。

首次使用：开机后手机连 "Xueersi-Setup" 热点 → 弹出配网页 → 选 WiFi → 输密码。

部署 (Windows cmd 用反斜杠，PowerShell/sh 用正斜杠)：
  uv run python scripts/flash.py upload apps\wifi_config.py
  uv run python scripts/flash.py upload apps\astronaut_watch.py :/main.py
  uv run python scripts/flash.py upload lib\st7735_buf.py
  uv run python scripts/flash.py upload lib\bigfont.py
  uv run python scripts/flash.py upload lib\easydisplay.py
  uv run python scripts/flash.py upload lib\weather.py
  uv run python scripts/flash.py upload lib\netease_hot.py
  uv run python scripts/flash.py upload lib\wifi_manager.py
  uv run python scripts/flash.py upload lib\captive_portal.py
  # 中文字库（务必传到板子 /font/ 目录）：
  uv run python scripts/flash.py upload font\text_lite_16px_2312.v3.bmf :/font/text_lite_16px_2312.v3.bmf

复位即运行。
"""
import sys
import time
import gc

sys.path.append("/lib")

from machine import Pin, SPI, RTC  # noqa: E402
import machine  # noqa: E402  (for machine.reset)
import st7735_buf as st  # noqa: E402
import bigfont as bf  # noqa: E402
import astro_icon  # noqa: E402
import easydisplay as ed  # noqa: E402
import weather as wx  # noqa: E402
import wifi_manager as wmgr  # noqa: E402
import webui as webui_mod  # noqa: E402
import local_sensor  # noqa: E402
import netease_hot  # noqa: E402

import wifi_config as cfg  # noqa: E402

# ---- 中文字库路径 ----
FONT_FILE = "/font/text_lite_16px_2312.v3.bmf"

# ---- 颜色 ----
BLACK = 0x0000
WHITE = 0xFFFF
CYAN = 0x07FF
GREEN = 0x07E0
YELLOW = 0xFFE0
RED = 0xF800
BLUE = 0x001F
GRAY = 0x7BEF
ORANGE = 0xFD20

# ---- 按键 ----
KEYS = {
    "up": 2,
    "down": 13,
    "left": 27,
    "right": 35,
    "a": 34,
    "b": 12,
}

# ---- 星期（中文字库支持） ----
WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


class KeyNav:
    """上拉按键边沿检测。返回刚按下的键名列表。"""

    def __init__(self):
        self.pins = {name: Pin(gpio, Pin.IN, Pin.PULL_UP)
                     for name, gpio in KEYS.items()}
        self.last = {name: 1 for name in KEYS}
        self.last_ms = 0

    def poll(self):
        now = time.ticks_ms()
        if time.ticks_diff(now, self.last_ms) < 35:
            return []
        self.last_ms = now
        hits = []
        for name, pin in self.pins.items():
            val = pin.value()
            if val == 0 and self.last.get(name, 1) == 1:
                hits.append(name)
            self.last[name] = val
        return hits


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


def show_status(disp, easydisp, msg, color=WHITE):
    """顶部状态条提示（中文走字库，缺失则英文）。"""
    disp.fill(0)
    disp.fill_rect(0, 0, 160, 14, BLUE)
    disp.text(msg[:26], 2, 3, color)
    disp.show()


def _char_units(ch):
    return 1 if ord(ch) < 128 else 2


def wrap_text(text, max_units=18, max_lines=0):
    """按 16px 中文字库半角宽度做粗略换行。"""
    if not text:
        return []
    lines = []
    line = ""
    units = 0
    for ch in text:
        if ch == "\n":
            if line:
                lines.append(line)
            line = ""
            units = 0
        else:
            w = _char_units(ch)
            if units + w > max_units and line:
                lines.append(line)
                line = ch
                units = w
            else:
                line += ch
                units += w
        if max_lines and len(lines) >= max_lines:
            break
    if line and (not max_lines or len(lines) < max_lines):
        lines.append(line)
    if max_lines and len(lines) == max_lines and len(text) > sum(len(x) for x in lines):
        last = lines[-1]
        lines[-1] = (last[:-1] + "...") if len(last) > 1 else "..."
    return lines


def draw_clock(disp, easydisp, now, ip, wifi_ok, weather_data, astro_frame=0, local_temp=""):
    """主界面渲染。now=localtime 元组。

    布局（160x128 横屏）：
      y=0~11   顶部状态栏：连网状态 + 右上温度快览
      y=16~40  太空人 + 大号时间 HH:MM（秒紧跟其后小号，同一行不换行）
      y=58~74  日期 + 星期（中文）
      y=96~127 天气区：图标 + 温度 + 湿度 + 状况文字（中文）
    """
    disp.fill(0)

    # ---- 顶部状态栏 (y=0~11) ----
    # 状态栏高 12px，只能放下 framebuf 自带 8x8 字体；中文字库 16px 放不下，
    # 且字库默认带黑色背景会盖掉绿底。故状态栏用 8x8 英文显示 IP/状态。
    bar = GREEN if wifi_ok else RED
    disp.fill_rect(0, 0, 160, 12, bar)
    status = ip if (wifi_ok and ip) else "OFFLINE"
    disp.text(status, 2, 2, BLACK)
    # 右上角温度快览
    if local_temp and (len(status) + len(local_temp)) * 8 <= 148:
        disp.text(local_temp[:5], 160 - len(local_temp[:5]) * 8 - 2, 2, BLACK)

    # ---- 左上：太空人 (x=2, y=18) ----
    astro_icon.draw(disp, 2, 18, WHITE, astro_frame)

    # ---- 右上：大号时间 HH:MM + 秒（同一行，左对齐，顶部齐平 y=16）----
    # 布局：HH:MM(scale=4) 从 x=54 起；秒(scale=3) 紧跟其后，间隔 6px。
    # 总宽 76+6+21=103，右边界 157，屏幕 160，不会被截断。
    time_str = "%02d:%02d" % (now[3], now[4])
    hm_scale = 4
    hm_x = 54
    bf.draw_text(disp, time_str, hm_x, 16, hm_scale, CYAN)

    # 秒：紧贴 HH:MM 右侧，底边与 HH:MM 对齐
    hm_w = bf.text_width(time_str, hm_scale)
    sec_str = "%02d" % now[5]
    sec_x = hm_x + hm_w + 6
    sec_y = 16 + (5 * hm_scale) - (5 * 3)
    bf.draw_text(disp, sec_str, sec_x, sec_y, 3, ORANGE)

    # ---- 中部：日期 + 星期 (y=58) ----
    date_str = "%02d-%02d" % (now[1], now[2])
    bf.draw_text(disp, date_str, 58, 58, 2, YELLOW)
    if easydisp:
        easydisp.text(WEEKDAYS[now[6] % 7], 112, 56, GRAY, show=False)
    else:
        en_week = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        bf.draw_text(disp, en_week[now[6] % 7], 112, 58, 2, GRAY)

    # ---- 底部：天气区 (y=92~127) ----
    disp.hline(0, 96, 160, GRAY)
    if weather_data:
        # 图标 (18x18)
        wx.draw_icon_for(disp, weather_data["cond"], 4, 102)
        # 温度 (大号黄) 在图标右侧
        bf.draw_text(disp, weather_data["temp"], 26, 104, 2, YELLOW)
        # 湿度
        bf.draw_text(disp, weather_data["humidity"], 80, 104, 2, CYAN)
        # 状况文字（中文走字库，英文则截断显示原描述）
        cond_cn = wx.condition_cn(weather_data["cond"]) if easydisp else None
        if easydisp and cond_cn:
            easydisp.text(cond_cn, 26, 116, WHITE, size=12, show=False)
        else:
            disp.text(weather_data["cond"][:16], 26, 118, WHITE)
    else:
        if easydisp:
            easydisp.text("天气加载中…", 2, 108, GRAY, show=False)
        else:
            disp.text("weather: loading...", 2, 108, GRAY)

    disp.show()


def draw_hot_comment(disp, easydisp, ip, wifi_ok, text, loading=False, err="",
                     scroll=0):
    """网易云热评页。"""
    disp.fill(0)
    disp.fill_rect(0, 0, 160, 14, BLUE if wifi_ok else RED)
    disp.text("NETEASE HOT", 2, 3, WHITE)
    disp.text("A/R refresh", 75, 3, YELLOW)

    if loading:
        if easydisp:
            easydisp.text("热评加载中", 28, 46, CYAN, show=False)
        else:
            disp.text("loading...", 36, 54, CYAN)
    elif err:
        if easydisp:
            easydisp.text(err, 8, 46, RED, show=False)
            easydisp.text("按A重试", 8, 72, GRAY, show=False)
        else:
            disp.text(err[:18], 8, 50, RED)
            disp.text("Press A retry", 8, 72, GRAY)
    elif text:
        disp.hline(0, 18, 160, GRAY)
        lines = wrap_text(text, max_units=18)
        max_scroll = max(0, len(lines) - 5)
        if scroll < 0:
            scroll = 0
        if scroll > max_scroll:
            scroll = max_scroll
        lines = lines[scroll:scroll + 5]
        y = 23
        for line in lines:
            if easydisp:
                easydisp.text(line, 8, y, WHITE, show=False)
            else:
                disp.text(line[:18], 8, y, WHITE)
            y += 19
    else:
        if easydisp:
            easydisp.text("暂无热评", 40, 50, GRAY, show=False)
        else:
            disp.text("No comment", 40, 54, GRAY)

    disp.hline(0, 112, 160, GRAY)
    bottom = "< > page  ^ v scroll"
    if wifi_ok and ip:
        bottom = ip[:15]
    disp.text(bottom, 2, 117, GRAY)
    disp.show()


def draw_weather_page(disp, easydisp, ip, wifi_ok, weather_data,
                      loading=False, err=""):
    """天气页：只在用户手动刷新后显示数据。"""
    disp.fill(0)
    disp.fill_rect(0, 0, 160, 14, BLUE if wifi_ok else RED)
    disp.text("WEATHER", 2, 3, WHITE)
    disp.text("A refresh", 88, 3, YELLOW)

    if loading:
        if easydisp:
            easydisp.text("天气刷新中", 28, 46, CYAN, show=False)
        else:
            disp.text("loading...", 36, 54, CYAN)
    elif err:
        if easydisp:
            easydisp.text(err, 8, 46, RED, show=False)
            easydisp.text("按A重试", 8, 72, GRAY, show=False)
        else:
            disp.text(err[:18], 8, 50, RED)
            disp.text("Press A retry", 8, 72, GRAY)
    elif weather_data:
        wx.draw_icon_for(disp, weather_data["cond"], 8, 34)
        bf.draw_text(disp, weather_data["temp"], 36, 32, 3, YELLOW)
        bf.draw_text(disp, weather_data["humidity"], 36, 60, 2, CYAN)
        cond_cn = wx.condition_cn(weather_data["cond"]) if easydisp else None
        if easydisp and cond_cn:
            easydisp.text(cond_cn, 36, 84, WHITE, show=False)
        else:
            disp.text(weather_data["cond"][:16], 36, 86, WHITE)
        disp.text(weather_data.get("wind", "")[:16], 36, 106, GRAY)
    else:
        if easydisp:
            easydisp.text("按A刷新天气", 24, 52, GRAY, show=False)
        else:
            disp.text("Press A refresh", 20, 58, GRAY)

    disp.hline(0, 112, 160, GRAY)
    bottom = "clock <  > hot"
    if wifi_ok and ip:
        bottom = ip[:15]
    disp.text(bottom, 2, 117, GRAY)
    disp.show()


def show_flash_mode_screen(disp, easydisp):
    """刷写模式待机界面：提示已就绪，可用 USB 上传。

    此界面不再做网络 IO，主程序在此软 sleep 等待，方便 USB 端的 Ctrl-C
    干净打断（flash.py upload 能可靠进 raw REPL）。
    """
    disp.fill(0)
    disp.fill_rect(0, 0, 160, 14, ORANGE)
    if easydisp:
        easydisp.text("刷写模式", 4, -1, BLACK, show=False)
        easydisp.text("USB 上传就绪", 4, 26, CYAN, show=False)
        easydisp.text("电脑执行:", 4, 50, WHITE, show=False)
        easydisp.text("flash.py upload", 4, 68, YELLOW, show=False)
        easydisp.text("传完按复位", 4, 96, GRAY, show=False)
    else:
        disp.text("FLASH MODE", 2, 3, BLACK)
        disp.text("USB upload ready", 2, 30, CYAN)
        disp.text("Run on PC:", 2, 50, WHITE)
        disp.text("flash.py upload", 2, 62, YELLOW)
        disp.text("Reset when done", 2, 96, GRAY)
    disp.show()


def main():
    disp = init_display()
    easydisp = init_easydisp(disp)
    show_status(disp, easydisp, "Booting...", WHITE)

    # 连 WiFi：无凭据或连不上时自动进入 AP 配网（配网成功后会重启）
    show_status(disp, easydisp, "Connecting WiFi...", YELLOW)
    wlan, ip = wmgr.ensure_connected(disp)
    if wlan:
        show_status(disp, easydisp, "Syncing time...", YELLOW)
        sync_ntp()
    else:
        show_status(disp, easydisp, "No WiFi - offline", RED)
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
                max_scroll = max(0, len(wrap_text(hot_comment, max_units=18)) - 5)
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
                    draw_hot_comment(disp, easydisp, ip, True, hot_comment,
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
                    draw_weather_page(disp, easydisp, ip, True, weather_data,
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
            draw_clock(disp, easydisp, now, ip, wlan is not None,
                       weather_data, astro_frame, local_temp)
        elif page == "hot" and hot_dirty:
            draw_hot_comment(disp, easydisp, ip, wlan is not None, hot_comment,
                             err=hot_error, scroll=hot_scroll)
            hot_dirty = False
        elif page == "weather" and weather_dirty:
            draw_weather_page(disp, easydisp, ip, wlan is not None, weather_data,
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
    show_flash_mode_screen(disp, easydisp)
    while True:
        time.sleep(1)   # Ctrl-C 能在此干净打断 → flash.py upload 可靠进 raw REPL


if __name__ == "__main__":
    main()
