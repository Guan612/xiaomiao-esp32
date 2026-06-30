"""学而思小喵掌机 (XiaoMiao) 引脚与硬件常量。

引脚定义来源：xueersi-xiaomiao 仓库 README。
主控 ESP32-D0WD-V3，4MB Flash + PSRAM。
"""

# ---- 按键（6 键，默认上拉，按下接地 = 0）----
KEY_UP = 2
KEY_DOWN = 13
KEY_LEFT = 27
KEY_RIGHT = 35
KEY_A = 34
KEY_B = 12
KEYS = {
    "up": KEY_UP,
    "down": KEY_DOWN,
    "left": KEY_LEFT,
    "right": KEY_RIGHT,
    "a": KEY_A,
    "b": KEY_B,
}
# 仅输入引脚（不可设为输出）
INPUT_ONLY_PINS = (34, 35, 36, 39)

# ---- TFT 显示屏 ST7735，SPI2，128x160 ----
TFT_WIDTH = 128
TFT_HEIGHT = 160
TFT_SCK = 18        # 与 SD 卡共享
TFT_MOSI = 23       # 与 SD 卡共享
TFT_CS = 5
TFT_DC = 4
TFT_RES = 19        # 与 SD 卡 MISO 共用

# ---- MicroSD 卡，SPI2 ----
SD_SCK = 18
SD_MOSI = 23
SD_MISO = 19
SD_CS = 22

# ---- 无源蜂鸣器（PWM/LEDC）----
BUZZER = 14

# ---- ADC 传感器 ----
LIGHT_SENSOR = 36   # ADC1_CH0 光照
TEMP_SENSOR = 39    # ADC1_CH3 热敏

# ---- I2C ----
I2C_SCL = 15
I2C_SDA = 21
I2C_MOTOR_LED_ADDR = 0x40  # 电机/LED 共用地址

# ---- UART0（原生串口）----
UART_TX = 1
UART_RX = 3

# ---- 预留扩展（PH2.0 3P 座）----
GPIO_RESERVED = (33, 32, 26, 25)


def key_pressed(pin_value: int) -> bool:
    """上拉按键：读到 0 视为按下。"""
    return pin_value == 0
