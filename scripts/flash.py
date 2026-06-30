"""常用操作封装。用法：
    uv run python scripts/flash.py erase
    uv run python scripts/flash.py firmware firmware\\xxx.bin
    uv run python scripts/flash.py firmware firmware\\xxx.bin 0x0
    uv run python scripts/flash.py micropython # 一键刷官方 MicroPython SPIRAM 固件（推荐）
    uv run python scripts/flash.py lvgl        # 一键刷上游 LVGL 固件（带屏幕驱动）
    uv run python scripts/flash.py framebuffer # 一键刷上游 framebuffer 固件
    uv run python scripts/flash.py upload apps\\hello.py
    uv run python scripts/flash.py repl

⚠️ 烧录地址说明（标准 ESP32）：
  - bootloader 起始镜像（含 bootloader+分区表+app 一体，MicroPython 官方固件都是这种）
    必须刷到 0x1000。刷到 0x0 会 bootloop（bootloader 错位，板子读不到 flash）。
  - 纯 app 镜像（不含 bootloader）刷到 0x10000。
"""
import os
import subprocess
import sys

# 端口：Windows 通常是 COMx，按需改；--port 也可在命令行覆盖
DEFAULT_PORT = os.environ.get("ESP32_PORT", "COM3")

# 上游仓库提供的固件（clone 到 upstream/bins/）
UPSTREAM_DIR = os.path.join(os.path.dirname(__file__), "..", "upstream", "bins")
# 官方 MicroPython 固件（从 micropython.org 下载后放 firmware/）
FIRMWARE_DIR = os.path.join(os.path.dirname(__file__), "..", "firmware")
FIRMWARES = {
    # 一体镜像（bootloader+分区表+app）刷到 0x1000；纯 app 镜像刷 0x10000
    "micropython": (FIRMWARE_DIR, "ESP32_GENERIC_SPIRAM-1.24.1.bin", "0x1000"),
    "lvgl": (UPSTREAM_DIR, "lvgl9.3_mpy_ESP32_GENERIC_SPIRAM_4MB_st7735.bin", "0x1000"),
    "framebuffer": (UPSTREAM_DIR, "ESP32_SPIRAM_1.24_SDCARDST7735.bin", "0x1000"),
}


def run(cmd):
    print("$", " ".join(cmd))
    subprocess.run(cmd, check=True)


def esptool_args(port, *extra):
    """统一通过 python -m 调用，避免 Windows 找不到 .py 入口。"""
    return [sys.executable, "-m", "esptool",
            "--chip", "esp32", "--port", port, *extra]


def mpremote_args(port, *extra):
    return [sys.executable, "-m", "mpremote", "connect", port, *extra]


def erase(port):
    run(esptool_args(port, "erase_flash"))


def flash(port, bin_path, address="0x10000"):
    """烧录单个固件。完整固件(含bootloader)用 0x0，app 用 0x10000。"""
    if not os.path.exists(bin_path):
        sys.exit(f"找不到固件文件: {bin_path}")
    run(esptool_args(port, "--baud", "460800", "write_flash", address, bin_path))


def flash_preset(port, name):
    """刷预设固件（micropython / lvgl / framebuffer），bin 来自 firmware/ 或 upstream/bins/。"""
    if name not in FIRMWARES:
        sys.exit(f"未知预设: {name}，可选: {list(FIRMWARES)}")
    base, fname, addr = FIRMWARES[name]
    bin_path = os.path.normpath(os.path.join(base, fname))
    if not os.path.exists(bin_path):
        sys.exit(f"找不到固件文件: {bin_path}（{name} 预设）")
    flash(port, bin_path, addr)


def upload(port, path, dest=None):
    """上传脚本/目录到板子。默认放到板子根目录。"""
    if os.path.isdir(path):
        run(mpremote_args(port, "cp", path, ":/"))
    else:
        dest = dest or f":/{os.path.basename(path)}"
        run(mpremote_args(port, "cp", path, dest))


def repl(port):
    run(mpremote_args(port, "repl"))


COMMANDS = {
    "erase": erase,
    "firmware": flash,
    "micropython": lambda port, *a: flash_preset(port, "micropython"),
    "lvgl": lambda port, *a: flash_preset(port, "lvgl"),
    "framebuffer": lambda port, *a: flash_preset(port, "framebuffer"),
    "upload": upload,
    "repl": repl,
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        print("命令:", ", ".join(COMMANDS))
        sys.exit(1)

    cmd = sys.argv[1]
    port = DEFAULT_PORT
    args = sys.argv[2:]
    # 支持 --port COM5 覆盖
    if "--port" in args:
        i = args.index("--port")
        port = args[i + 1]
        args = args[:i] + args[i + 2:]

    COMMANDS[cmd](port, *args)


if __name__ == "__main__":
    main()
