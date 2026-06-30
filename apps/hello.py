"""点亮屏幕 + 按键测试。上传到板子后用 mpremote 运行。

本地预览：uv run mpremote run apps/hello.py
注意：必须连着板子，因为要用到 machine/st7735 等硬件模块。
"""
import sys
import time

sys.path.append("/lib")  # 若把 xiaomiao.py 放到板子 /lib 下

try:
    from machine import Pin, SPI, PWM
    import xiaomiao as hw
except ImportError:
    print("需在板子上运行；本机仅作语法检查用。")
    raise


def scan_keys():
    """返回当前按下的键名列表。"""
    pressed = []
    for name, gpio in hw.KEYS.items():
        p = Pin(gpio, Pin.IN, Pin.PULL_UP)
        if hw.key_pressed(p.value()):
            pressed.append(name)
    return pressed


def beep(freq=2000, ms=80):
    """蜂鸣器短鸣。"""
    buz = PWM(Pin(hw.BUZZER), freq=freq, duty=512)
    time.sleep_ms(ms)
    buz.deinit()


def main():
    print("小喵掌机 hello，5 秒内按键测试...")
    beep(262, 100)
    for _ in range(50):
        k = scan_keys()
        if k:
            print("按下:", k)
        time.sleep_ms(100)
    print("done")


if __name__ == "__main__":
    main()
