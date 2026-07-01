"""Probe XiaoMiao battery-related signals.

Run on the board from mpremote:
    uv run python -m mpremote connect COM3 run apps/battery_probe.py

Or upload then run from REPL:
    uv run python scripts/flash.py upload apps/battery_probe.py
    >>> import battery_probe

This script does not know the board's battery wiring. It scans I2C for a
possible power-management / fuel-gauge chip and samples common ESP32 ADC pins.
If VBAT is connected through a divider, one ADC value should stay around a
stable fraction of the battery voltage.
"""
import time

from machine import ADC, I2C, Pin


I2C_SCL = 15
I2C_SDA = 21

# XiaoMiao known pins:
# 36 = light sensor, 39 = thermistor, 34/35 = keys, 32/33/25/26 = expansion.
ADC_PINS = (32, 33, 34, 35, 36, 39)
ADC_MAX = 4095

# Approximate Li-ion open-circuit voltage to percentage curve.
BATTERY_CURVE = (
    (4.20, 100),
    (4.10, 90),
    (4.00, 80),
    (3.92, 70),
    (3.85, 60),
    (3.79, 50),
    (3.73, 40),
    (3.68, 30),
    (3.61, 20),
    (3.50, 10),
    (3.30, 0),
)


def _setup_adc(pin):
    adc = ADC(Pin(pin))
    try:
        adc.atten(ADC.ATTN_11DB)
    except Exception:
        pass
    try:
        adc.width(ADC.WIDTH_12BIT)
    except Exception:
        pass
    return adc


def _read_avg(adc, samples=32):
    total = 0
    for _ in range(samples):
        total += adc.read()
        time.sleep_ms(2)
    return total / samples


def _read_voltage(adc, raw):
    if hasattr(adc, "read_uv"):
        try:
            return adc.read_uv() / 1000000.0
        except Exception:
            pass
    # Fallback is a rough estimate for ATTEN_11DB on ESP32 MicroPython.
    return raw / ADC_MAX * 3.3


def battery_percent(voltage):
    if voltage >= BATTERY_CURVE[0][0]:
        return 100
    if voltage <= BATTERY_CURVE[-1][0]:
        return 0
    for i in range(len(BATTERY_CURVE) - 1):
        high_v, high_p = BATTERY_CURVE[i]
        low_v, low_p = BATTERY_CURVE[i + 1]
        if high_v >= voltage >= low_v:
            span = high_v - low_v
            if span <= 0:
                return low_p
            return int(low_p + (voltage - low_v) * (high_p - low_p) / span + 0.5)
    return 0


def scan_i2c():
    print("I2C scan on SCL=%d SDA=%d" % (I2C_SCL, I2C_SDA))
    try:
        i2c = I2C(0, scl=Pin(I2C_SCL), sda=Pin(I2C_SDA))
        addrs = i2c.scan()
    except Exception as exc:
        print("  failed:", exc)
        return
    if not addrs:
        print("  no devices")
        return
    print("  devices:", ", ".join("0x%02X" % a for a in addrs))
    print("  note: 0x40 is known motor/LED on this board")


def probe_adc(rounds=20):
    adcs = []
    for pin in ADC_PINS:
        try:
            adcs.append((pin, _setup_adc(pin)))
        except Exception as exc:
            print("ADC GPIO%d unavailable: %s" % (pin, exc))

    print("")
    print("ADC probe. Columns: pin raw adc_v vbat_if_2x percent_if_2x")
    print("If battery uses a 1:1 divider, vbat_if_2x is the estimated battery voltage.")
    for n in range(rounds):
        print("")
        print("round", n + 1)
        for pin, adc in adcs:
            raw = _read_avg(adc)
            adc_v = _read_voltage(adc, raw)
            vbat_2x = adc_v * 2.0
            pct = battery_percent(vbat_2x)
            print(
                "  GPIO%-2d raw=%4d adc=%.3fV 2x=%.3fV %3d%%"
                % (pin, int(raw + 0.5), adc_v, vbat_2x, pct)
            )
        time.sleep_ms(500)


def main():
    print("XiaoMiao battery probe")
    print("Press Ctrl+C to stop.")
    scan_i2c()
    probe_adc()
    print("")
    print("done")


main()
