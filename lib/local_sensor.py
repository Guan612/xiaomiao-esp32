"""Local ADC sensors for XiaoMiao.

GPIO39 is the onboard thermistor input. The conversion uses a common
10K NTC/B3950 divider model; tune the constants below if the board reads high
or low against a known thermometer.
"""
import math
from machine import ADC, Pin

TEMP_PIN = 39
LIGHT_PIN = 36
ADC_MAX = 4095

TEMP_NOMINAL_C = 25.0
TEMP_NOMINAL_OHMS = 10000.0
TEMP_BETA = 3950.0
TEMP_SERIES_OHMS = 10000.0

_temp_adc = None
_light_adc = None


def _setup_adc(adc):
    try:
        adc.atten(ADC.ATTN_11DB)
    except Exception:
        pass
    try:
        adc.width(ADC.WIDTH_12BIT)
    except Exception:
        pass
    return adc


def _temp():
    global _temp_adc
    if _temp_adc is None:
        _temp_adc = _setup_adc(ADC(Pin(TEMP_PIN)))
    return _temp_adc


def _light():
    global _light_adc
    if _light_adc is None:
        _light_adc = _setup_adc(ADC(Pin(LIGHT_PIN)))
    return _light_adc


def _read_avg(adc, samples=8):
    total = 0
    for _ in range(samples):
        total += adc.read()
    return total / samples


def temperature_raw(samples=8):
    return _read_avg(_temp(), samples)


def light_raw(samples=8):
    return _read_avg(_light(), samples)


def temperature_c(samples=8, raw=None):
    if raw is None:
        raw = temperature_raw(samples)
    if raw <= 0 or raw >= ADC_MAX:
        return None

    # Voltage divider: Vout = Vcc * Rntc / (Rseries + Rntc).
    r_ntc = TEMP_SERIES_OHMS * raw / (ADC_MAX - raw)
    if r_ntc <= 0:
        return None

    inv_t = (1.0 / (TEMP_NOMINAL_C + 273.15)) + (math.log(r_ntc / TEMP_NOMINAL_OHMS) / TEMP_BETA)
    return (1.0 / inv_t) - 273.15


def temperature_label():
    c = temperature_c()
    if c is None:
        return ""
    return "%dC" % int(c + 0.5)


def light_label(samples=8):
    raw = light_raw(samples)
    return "%d" % int(raw + 0.5)


def entropy_sample(samples=4):
    """Return sensor readings useful for seeding small UI randomness."""
    temp_raw = temperature_raw(samples)
    light = light_raw(samples)
    temp_c = temperature_c(raw=temp_raw)
    temp_part = 0 if temp_c is None else int(temp_c * 100)
    seed = int(temp_raw) ^ (int(light) << 5) ^ temp_part
    temp_text = "" if temp_c is None else "%dC" % int(temp_c + 0.5)
    return {
        "seed": seed,
        "temp_raw": int(temp_raw),
        "light_raw": int(light),
        "temp": temp_text,
        "light": "%d" % int(light + 0.5),
    }
