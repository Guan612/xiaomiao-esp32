"""Local ADC sensors for XiaoMiao.

GPIO39 is the onboard thermistor input. The conversion uses a common
10K NTC/B3950 divider model; tune the constants below if the board reads high
or low against a known thermometer.
"""
import math
from machine import ADC, Pin

TEMP_PIN = 39
ADC_MAX = 4095

TEMP_NOMINAL_C = 25.0
TEMP_NOMINAL_OHMS = 10000.0
TEMP_BETA = 3950.0
TEMP_SERIES_OHMS = 10000.0

_temp_adc = None


def _adc():
    global _temp_adc
    if _temp_adc is None:
        _temp_adc = ADC(Pin(TEMP_PIN))
        try:
            _temp_adc.atten(ADC.ATTN_11DB)
        except Exception:
            pass
        try:
            _temp_adc.width(ADC.WIDTH_12BIT)
        except Exception:
            pass
    return _temp_adc


def temperature_c(samples=8):
    total = 0
    adc = _adc()
    for _ in range(samples):
        total += adc.read()
    raw = total / samples
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
