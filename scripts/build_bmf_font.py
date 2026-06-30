"""Build a ufont BMF v3 font from a TrueType/OpenType font.

The generated file matches the format consumed by lib/easydisplay.py:
16-byte header, sorted big-endian Unicode code table, then MONO_HLSB bitmaps.
"""
from pathlib import Path
import argparse
import struct

from PIL import Image, ImageDraw, ImageFont


BASE_RANGES = (
    (0x20, 0x7E),       # ASCII
    (0xA0, 0xFF),       # Latin-1 punctuation/symbols
    (0x2000, 0x206F),   # General punctuation
    (0x3000, 0x303F),   # CJK symbols and punctuation
    (0xFF00, 0xFFEF),   # Halfwidth and fullwidth forms
)


EXTRA_CHARS = "℃°←↑→↓↖↗↘↙"


def iter_codes():
    codes = set()
    for start, end in BASE_RANGES:
        codes.update(range(start, end + 1))
    for code in range(0x4E00, 0xA000):
        try:
            chr(code).encode("gb2312")
        except UnicodeEncodeError:
            continue
        codes.add(code)
    codes.update(ord(ch) for ch in EXTRA_CHARS)
    return sorted(codes)


def glyph_bitmap(font, ch, size):
    canvas_size = size * 3
    image = Image.new("L", (canvas_size, canvas_size), 0)
    draw = ImageDraw.Draw(image)
    bbox = draw.textbbox((0, 0), ch, font=font)
    glyph_w = bbox[2] - bbox[0]
    glyph_h = bbox[3] - bbox[1]
    x = (canvas_size - glyph_w) // 2 - bbox[0]
    y = (canvas_size - glyph_h) // 2 - bbox[1]
    draw.text((x, y), ch, 255, font=font)

    left = (canvas_size - size) // 2
    top = (canvas_size - size) // 2
    return image.crop((left, top, left + size, top + size))


def pack_mono_hlsb(image, threshold=96):
    width, height = image.size
    data = bytearray(height * ((width + 7) // 8))
    pixels = image.load()
    row_bytes = (width + 7) // 8
    for y in range(height):
        for x in range(width):
            if pixels[x, y] >= threshold:
                data[y * row_bytes + (x // 8)] |= 1 << (7 - x % 8)
    return bytes(data)


def build(font_path, output_path, size, ascii_font_path=None):
    font = ImageFont.truetype(str(font_path), size)
    ascii_font = ImageFont.truetype(str(ascii_font_path), size) if ascii_font_path else font
    codes = iter_codes()
    bitmap_size = size * ((size + 7) // 8)
    map_bytes = b"".join(struct.pack(">H", code) for code in codes)
    start_bitmap = 16 + len(map_bytes)
    if start_bitmap > 0xFFFFFF:
        raise ValueError("font map is too large for BMF v3 header")

    header = bytearray(16)
    header[0:2] = b"BM"
    header[2] = 3
    header[3] = 0
    header[4:7] = start_bitmap.to_bytes(3, "big")
    header[7] = size
    header[8] = bitmap_size

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as out:
        out.write(header)
        out.write(map_bytes)
        for code in codes:
            glyph_font = ascii_font if code < 128 else font
            bitmap = glyph_bitmap(glyph_font, chr(code), size)
            out.write(pack_mono_hlsb(bitmap))

    print("codes:", len(codes))
    print("bitmap_size:", bitmap_size)
    print("start_bitmap:", start_bitmap)
    print("output:", output_path)
    print("bytes:", output_path.stat().st_size)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--font", default=r"C:\Windows\Fonts\NotoSansSC-VF.ttf")
    parser.add_argument("--ascii-font", default=None,
                        help="Optional font used for ASCII glyphs only.")
    parser.add_argument("--output", default="font/noto_sans_sc_16px_gb2312.v3.bmf")
    parser.add_argument("--size", type=int, default=16)
    args = parser.parse_args()
    build(Path(args.font), Path(args.output), args.size,
          Path(args.ascii_font) if args.ascii_font else None)


if __name__ == "__main__":
    main()
