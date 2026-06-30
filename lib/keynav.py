"""小喵掌机按键边沿检测。"""
import time
from machine import Pin


KEYS = {
    "up": 2,
    "down": 13,
    "left": 27,
    "right": 35,
    "a": 34,
    "b": 12,
}


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
