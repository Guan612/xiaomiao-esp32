r"""WiFi 太空人手表（含天气 + AP 配网 + 中文字库）。

功能：
  1. AP 配网：无 WiFi 凭据(或连不上)时，板子开热点，手机连上后自动弹配网页
     选 WiFi、输密码，存盘重启后自动连接。详情见 lib/captive_portal.py。
  2. NTP 对时（aliyun, UTC+8）
  3. wttr.in 拉天气（免 key，自动 IP 定位或指定城市）
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
import st7735_buf as st  # noqa: E402
import bigfont as bf  # noqa: E402
import easydisplay as ed  # noqa: E402
import weather as wx  # noqa: E402
import wifi_manager as wmgr  # noqa: E402

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

# ---- 星期（中文字库支持） ----
WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


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


def draw_clock(disp, easydisp, now, ip, wifi_ok, weather_data):
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
    status = ("ON " + ip[:14]) if (wifi_ok and ip) else "OFFLINE"
    disp.text(status, 2, 2, BLACK)
    # 右上角温度快览
    if weather_data:
        disp.text(weather_data["temp"][:8], 122, 2, BLACK)

    # ---- 左上：太空人 (x=2, y=16) ----
    bf.draw_astronaut(disp, 2, 16)

    # ---- 右上：大号时间 HH:MM + 秒（同一行，左对齐，顶部齐平 y=16）----
    # 布局：HH:MM(scale=4) 从 x=30 起；秒(scale=3) 紧跟其后，间隔 6px。
    # 总宽 76+6+21=103，右边界 133，屏幕 160，留 27px 余量，不会被截断。
    time_str = "%02d:%02d" % (now[3], now[4])
    hm_scale = 4
    hm_x = 30
    bf.draw_text(disp, time_str, hm_x, 16, hm_scale, CYAN)

    # 秒：紧贴 HH:MM 右侧，顶部对齐(都 y=16)，橙色小一号
    hm_w = bf.text_width(time_str, hm_scale)
    sec_str = "%02d" % now[5]
    sec_x = hm_x + hm_w + 6
    bf.draw_text(disp, sec_str, sec_x, 16, 3, ORANGE)

    # ---- 中部：日期 + 星期 (y=58) ----
    date_str = "%02d-%02d" % (now[1], now[2])
    bf.draw_text(disp, date_str, 40, 58, 2, YELLOW)
    if easydisp:
        easydisp.text(WEEKDAYS[now[6] % 7], 100, 56, GRAY, show=False)
    else:
        en_week = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        bf.draw_text(disp, en_week[now[6] % 7], 100, 58, 2, GRAY)

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
            easydisp.text(cond_cn, 2, 122, WHITE, show=False)
        else:
            disp.text(weather_data["cond"][:24], 2, 120, WHITE)
    else:
        if easydisp:
            easydisp.text("天气加载中…", 2, 108, GRAY, show=False)
        else:
            disp.text("weather: loading...", 2, 108, GRAY)

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
        show_status(disp, easydisp, "Fetching weather...", YELLOW)
    else:
        show_status(disp, easydisp, "No WiFi - offline", RED)
        time.sleep(1)

    # 立即拉一次天气
    weather_data = None
    if wlan:
        weather_data = wx.fetch(cfg.WEATHER_CITY)

    last_ntp = time.time()
    last_weather = time.time()

    while True:
        now = time.localtime()
        draw_clock(disp, easydisp, now, ip, wlan is not None, weather_data)
        gc.collect()

        # 定时 NTP（每小时）
        if wlan and (time.time() - last_ntp > 3600):
            try:
                sync_ntp()
                last_ntp = time.time()
            except Exception:
                pass

        # 定时刷新天气
        if wlan and (time.time() - last_weather > cfg.WEATHER_INTERVAL):
            try:
                new_w = wx.fetch(cfg.WEATHER_CITY)
                if new_w:
                    weather_data = new_w
                last_weather = time.time()
            except Exception as e:
                print("weather refresh fail:", e)

        time.sleep_ms(500)


if __name__ == "__main__":
    main()
