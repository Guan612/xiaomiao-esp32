"""点亮屏幕 demo（自包含，不依赖仓库缺失的 lib）。

功能：屏幕显示标题 + 实时按键状态 + 蜂鸣器反馈。

部署：把这些文件传到板子后运行：
    uv run python scripts/flash.py upload lib/st7735_buf.py
    uv run python scripts/flash.py upload apps/hello_screen.py :/main.py
    # 复位即运行；或 mpremote 执行：
    uv run python scripts/flash.py exec "import hello_screen"
"""
import sys
import time

sys.path.append("/lib")

from machine import Pin, SPI, PWM  # noqa: E402
import st7735_buf as st  # noqa: E402

# ---- 屏幕：160x128 横屏（rotate=1 横向）----
spi = SPI(2, baudrate=20000000, polarity=0, phase=0,
          sck=Pin(18), mosi=Pin(23))
disp = st.ST7735(width=160, height=128, spi=spi, cs=5, dc=4, res=19,
                 rotate=1, bl=None, invert=False, rgb=True)

# ---- 颜色 ----
WHITE = st.WHITE
RED = st.RED
GREEN = st.GREEN
BLUE = st.BLUE
YELLOW = st.YELLOW
CYAN = st.CYAN

# ---- 6 键 ----
KEYS = {"UP": 2, "DOWN": 13, "LEFT": 27, "RIGHT": 35, "A": 34, "B": 12}
pins = {name: Pin(gpio, Pin.IN, Pin.PULL_UP) for name, gpio in KEYS.items()}

# ---- 蜂鸣器 ----
def beep(freq=2000, ms=60):
    buz = PWM(Pin(14), freq=freq, duty=512)
    time.sleep_ms(ms)
    buz.deinit()


def draw_frame():
    disp.fill(0)
    # 标题
    disp.fill_rect(0, 0, 160, 20, BLUE)
    disp.text("XiaoMiao", 4, 6, WHITE)
    # 三个色块（验证颜色）
    disp.fill_rect(8, 30, 40, 20, RED)
    disp.fill_rect(60, 30, 40, 20, GREEN)
    disp.fill_rect(112, 30, 40, 20, CYAN)
    # 边框
    disp.rect(0, 0, 160, 128, WHITE)
    disp.show()


def main():
    print("hello_screen start")
    beep(880, 80)
    last_any = False
    while True:
        draw_frame()
        # 按键状态行
        pressed = [n for n in KEYS if pins[n].value() == 0]
        y = 64
        disp.text("Keys:", 4, y, YELLOW)
        if pressed:
            disp.text(",".join(pressed), 44, y, RED)
            if not last_any:
                beep(1200, 40)  # 新按下时响一下
            last_any = True
        else:
            disp.text("-", 44, y, WHITE)
            last_any = False
        disp.show()
        time.sleep_ms(80)


if __name__ == "__main__":
    main()
