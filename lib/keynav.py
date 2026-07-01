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

    def __init__(self, long_ms=800, poll_ms=20):
        self.pins = {name: Pin(gpio, Pin.IN, Pin.PULL_UP)
                     for name, gpio in KEYS.items()}
        self.last = {name: 1 for name in KEYS}
        self.down_ms = {name: 0 for name in KEYS}
        self.long_sent = {name: False for name in KEYS}
        self.last_ms = 0
        self.long_ms = long_ms
        self.poll_ms = poll_ms

    def poll(self):
        now = time.ticks_ms()
        if time.ticks_diff(now, self.last_ms) < self.poll_ms:
            return []
        self.last_ms = now
        hits = []
        for name, pin in self.pins.items():
            val = pin.value()
            if val == 0 and self.last.get(name, 1) == 1:
                hits.append(name)
                self.down_ms[name] = now
                self.long_sent[name] = False
            elif val == 0 and not self.long_sent.get(name, False):
                if time.ticks_diff(now, self.down_ms.get(name, now)) >= self.long_ms:
                    hits.append(name + "_long")
                    self.long_sent[name] = True
            elif val == 1 and self.last.get(name, 1) == 0:
                self.down_ms[name] = 0
                self.long_sent[name] = False
            self.last[name] = val
        return hits
