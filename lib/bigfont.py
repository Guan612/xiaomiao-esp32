"""大号像素字体 (3x5 点阵) + 太空人精灵绘制。

不依赖任何外部字库/图片，纯程序化生成，160x128 横屏专用。
供 astronaut_watch.py 使用。
"""

# 每个数字用 5 个字符串表示 3 列 x 5 行的点阵（'X'=点亮）
DIGITS = {
    '0': ["XXX",
          "X.X",
          "X.X",
          "X.X",
          "XXX"],
    '1': [".X.",
          "XX.",
          ".X.",
          ".X.",
          "XXX"],
    '2': ["XXX",
          "..X",
          "XXX",
          "X..",
          "XXX"],
    '3': ["XXX",
          "..X",
          "XXX",
          "..X",
          "XXX"],
    '4': ["X.X",
          "X.X",
          "XXX",
          "..X",
          "..X"],
    '5': ["XXX",
          "X..",
          "XXX",
          "..X",
          "XXX"],
    '6': ["XXX",
          "X..",
          "XXX",
          "X.X",
          "XXX"],
    '7': ["XXX",
          "..X",
          "..X",
          "..X",
          "..X"],
    '8': ["XXX",
          "X.X",
          "XXX",
          "X.X",
          "XXX"],
    '9': ["XXX",
          "X.X",
          "XXX",
          "..X",
          "XXX"],
    ':': ["...",
          ".X.",
          "...",
          ".X.",
          "..."],
    ' ': ["...",
          "...",
          "...",
          "...",
          "..."],
}


def draw_char(disp, ch, x, y, scale, color):
    """绘制单个字符，scale=放大倍数（1=3x5像素，3=9x15像素）。"""
    pattern = DIGITS.get(ch, DIGITS[' '])
    for row in range(5):
        line = pattern[row]
        for col in range(3):
            if line[col] == 'X':
                px = x + col * scale
                py = y + row * scale
                disp.fill_rect(px, py, scale, scale, color)


def draw_text(disp, text, x, y, scale, color, spacing=1):
    """绘制字符串。每个字符宽 3*scale，间隔 spacing*scale。"""
    step = (3 + spacing) * scale
    for i, ch in enumerate(text):
        draw_char(disp, ch, x + i * step, y, scale, color)


def text_width(text, scale, spacing=1):
    return len(text) * (3 + spacing) * scale - spacing * scale


# ---------- 太空人精灵 ----------
# 像素风太空人，26x26（在 framebuffer 上 scale=1 即可）
# 字符编码：空格=透明, 字母=颜色键
# 实际渲染时用 fill_rect 一个个画。
# 用 'W'=白 'H'=头盔橙边 'F'=脸 'G'=灰 'B'=蓝衣 'Y'=黄 'K'=黑 ' '=透明
ASTRONAUT = [
    "                          ",
    "          WWWWW           ",
    "        WWWHHHHHWW        ",
    "       WHHHHHHHHHHW       ",
    "      WHHFFFFFFFHHW       ",
    "      WHHFKFFFFKFHW       ",   # 眼睛
    "      WHHFFFFFFFH W       ",
    "      WHHFFFFFFFFHW       ",
    "       WHHHHHHHHHHW       ",
    "        WWWWWWWWWW        ",
    "       BBBBBBBBBBBB       ",   # 身体
    "      BBYYYYYYYYBBYB      ",
    "     BBYYYYYYYYYYBYB      ",
    "     BBYYYYBBBBYYBYB      ",
    "     BBYYYBBYYBBYYBYB     ",
    "     BBYYYBBYYBBYYBYB     ",
    "     BBYYYYBBBBYYBYB      ",
    "      BBYYYYYYYYBYB       ",
    "       BBBBBBBBBBB        ",
    "        BBBBBBBBB         ",
    "         GGGGGG           ",   # 腿
    "         GG  GG           ",
    "         GG  GG           ",
    "         GG  GG           ",
    "                          ",
    "                          ",
]

ASTRO_COLORS = {
    'W': 0xFFFF,  # 白
    'H': 0xFD20,  # 橙
    'F': 0xFFBE,  # 肤色
    'K': 0x0000,  # 黑
    'B': 0x001F,  # 蓝
    'Y': 0xFFE0,  # 黄
    'G': 0x7BEF,  # 灰
}


def draw_astronaut(disp, x, y):
    """在 (x,y) 绘制太空人（26 宽 x 26 高，像素 1:1）。"""
    for row, line in enumerate(ASTRONAUT):
        for col, ch in enumerate(line):
            if ch == ' ':
                continue
            color = ASTRO_COLORS.get(ch)
            if color is None:
                continue
            disp.pixel(x + col, y + row, color)
