"""太空人手表 UI 绘制函数。"""
import astro_icon
import bigfont as bf
import weather as wx


BLACK = 0x0000
WHITE = 0xFFFF
CYAN = 0x07FF
GREEN = 0x07E0
YELLOW = 0xFFE0
RED = 0xF800
BLUE = 0x001F
GRAY = 0x7BEF
ORANGE = 0xFD20

WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def show_status(disp, easydisp, msg, color=WHITE):
    """顶部状态条提示。"""
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


def draw_clock(disp, easydisp, now, ip, wifi_ok, weather_data,
               astro_frame=0, local_temp=""):
    """主时钟页。"""
    disp.fill(0)

    bar = GREEN if wifi_ok else RED
    disp.fill_rect(0, 0, 160, 12, bar)
    status = ip if (wifi_ok and ip) else "OFFLINE"
    disp.text(status, 2, 2, BLACK)
    if local_temp and (len(status) + len(local_temp)) * 8 <= 148:
        disp.text(local_temp[:5], 160 - len(local_temp[:5]) * 8 - 2, 2, BLACK)

    astro_icon.draw(disp, 2, 18, WHITE, astro_frame)

    time_str = "%02d:%02d" % (now[3], now[4])
    hm_scale = 4
    hm_x = 54
    bf.draw_text(disp, time_str, hm_x, 16, hm_scale, CYAN)

    hm_w = bf.text_width(time_str, hm_scale)
    sec_str = "%02d" % now[5]
    sec_x = hm_x + hm_w + 6
    sec_y = 16 + (5 * hm_scale) - (5 * 3)
    bf.draw_text(disp, sec_str, sec_x, sec_y, 3, ORANGE)

    date_str = "%02d-%02d" % (now[1], now[2])
    bf.draw_text(disp, date_str, 58, 58, 2, YELLOW)
    if easydisp:
        easydisp.text(WEEKDAYS[now[6] % 7], 112, 56, GRAY, show=False)
    else:
        en_week = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        bf.draw_text(disp, en_week[now[6] % 7], 112, 58, 2, GRAY)

    disp.hline(0, 96, 160, GRAY)
    if weather_data:
        wx.draw_icon_for(disp, weather_data["cond"], 4, 102)
        bf.draw_text(disp, weather_data["temp"], 26, 104, 2, YELLOW)
        bf.draw_text(disp, weather_data["humidity"], 80, 104, 2, CYAN)
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
    disp.text("HOT", 2, 3, WHITE)
    disp.text("A refresh", 84, 3, YELLOW)

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
        y = 24
        for line in lines:
            if easydisp:
                easydisp.text(line, 8, y, WHITE, show=False)
            else:
                disp.text(line[:18], 8, y, WHITE)
            y += 18
    else:
        if easydisp:
            easydisp.text("暂无热评", 40, 50, GRAY, show=False)
        else:
            disp.text("No comment", 40, 54, GRAY)

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
        wx.draw_icon_for(disp, weather_data["cond"], 8, 30)
        cond_cn = wx.condition_cn(weather_data["cond"]) if easydisp else None
        if easydisp and cond_cn:
            easydisp.text(cond_cn, 34, 26, WHITE, show=False)
        else:
            disp.text(weather_data["cond"][:15], 34, 30, WHITE)

        temp = weather_data.get("temp", "")
        humidity = weather_data.get("humidity", "")
        wind = weather_data.get("wind", "")
        disp.text(("T " + temp)[:19], 8, 56, YELLOW)
        disp.text(("H " + humidity)[:19], 8, 72, CYAN)
        disp.text(("W " + wind)[:19], 8, 88, GRAY)
    else:
        if easydisp:
            easydisp.text("按A刷新天气", 24, 52, GRAY, show=False)
        else:
            disp.text("Press A refresh", 20, 58, GRAY)

    disp.show()


def show_flash_mode_screen(disp, easydisp):
    """刷写模式待机界面。"""
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
