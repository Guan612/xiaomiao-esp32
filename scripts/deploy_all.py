"""一键部署全部改动文件到 ESP32（单串口连接，raw REPL 小块分块，可靠）。

背景：main.py 开机自启占串口 + 关闭串口会触发板子复位，导致 mpremote 不可靠。
本脚本在【单次串口连接】内打断 main.py、保持 raw REPL，逐文件分块 base64 写入，
最后软复位运行。每块很小（300B 原始）保证 raw REPL 命令缓冲不溢出。

用法：
  uv run python scripts/deploy_all.py            # 传全部
  uv run python scripts/deploy_all.py --no-font  # 不传字库（已传过时）
"""
import base64
import os
import serial
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PORT = os.environ.get("ESP32_PORT", "COM3")

# (本地相对 ROOT 的路径, 板子绝对路径)
FILES = [
    ("lib/st7735_buf.py",         "/lib/st7735_buf.py"),
    ("lib/bigfont.py",            "/lib/bigfont.py"),
    ("lib/easydisplay.py",        "/lib/easydisplay.py"),
    ("lib/watch_ui.py",           "/lib/watch_ui.py"),
    ("lib/keynav.py",             "/lib/keynav.py"),
    ("lib/astro_icon.py",         "/lib/astro_icon.py"),
    ("lib/local_sensor.py",       "/lib/local_sensor.py"),
    ("lib/weather.py",            "/lib/weather.py"),
    ("lib/netease_hot.py",        "/lib/netease_hot.py"),
    ("lib/wifi_manager.py",       "/lib/wifi_manager.py"),
    ("lib/captive_portal.py",     "/lib/captive_portal.py"),
    ("lib/webui.py",              "/lib/webui.py"),
    ("apps/astronaut_watch.py",   "/main.py"),
    ("font/text_lite_16px_2312.v3.bmf", "/font/text_lite_16px_2312.v3.bmf"),
]


def open_and_halt(port):
    s = serial.Serial(port, 115200, timeout=1, dsrdtr=False, rtscts=False)
    s.dtr = False
    s.rts = False
    time.sleep(0.5)
    end = time.time() + 0.8
    while time.time() < end:
        if not s.read(256):
            break
        time.sleep(0.05)
    for _ in range(4):
        s.write(b'\x03')
        time.sleep(0.4)
    time.sleep(0.6)
    end = time.time() + 1.0
    while time.time() < end:
        if not s.read(256):
            break
        time.sleep(0.05)
    return s


def exec_raw(s, code, timeout=12):
    """在 raw REPL 执行代码，返回输出。每次重进 raw 以获得干净状态。

    变量 f、D 在同一会话内跨多次 exec_raw 保持（raw REPL 不清会话变量）。
    """
    if isinstance(code, str):
        code = code.encode('utf-8')
    s.write(b'\x03')            # Ctrl-C 打断（防板子在跑 main.py）
    time.sleep(0.15)
    s.read(256)
    s.write(b'\x02')            # Ctrl-B 回 friendly
    time.sleep(0.12)
    s.read(256)
    s.write(b'\x01')            # Ctrl-A 进 raw
    time.sleep(0.4)
    head = s.read(256) or b''
    if b'>' not in head:
        raise RuntimeError("进 raw REPL 失败: %r" % head[-80:])
    s.write(code)
    s.write(b'\x04')            # Ctrl-D 执行
    out = b''
    end = time.time() + timeout
    while time.time() < end:
        d = s.read(512)
        if d:
            out += d
            if out.endswith(b'\x04>'):
                break
        else:
            time.sleep(0.02)
    text = out.decode('utf-8', 'replace')
    if '\x04' in text:
        stdout, _, stderr = text.partition('\x04')
        stderr = stderr.replace('\x04>', '').strip()
        if 'Traceback' in stderr:
            raise RuntimeError("执行出错: %s" % stderr)
        return stdout
    return text


def upload(s, local_rel, remote, chunk=300):
    """分块 base64 写入。f、D 句柄跨块保持。"""
    local = os.path.join(ROOT, local_rel.replace('/', os.sep))
    with open(local, 'rb') as f:
        data = f.read()
    total = len(data)

    parent = remote.rsplit('/', 1)[0]
    exec_raw(s,
        "import os,ubinascii as D\n"
        "try:\n"
        "    os.mkdir(%r)\n"
        "except OSError:\n"
        "    pass\n" % parent)
    r = exec_raw(s, "f=open(%r,'wb')\n" % remote)
    if 'Traceback' in r:
        raise RuntimeError("打开 %s 失败: %s" % (remote, r))

    off = 0
    last_report = 0
    while off < total:
        piece = data[off:off + chunk]
        b64 = base64.b64encode(piece).decode('ascii')
        r = exec_raw(s, "f.write(D.a2b_base64(%r))\n" % b64)
        if 'Traceback' in r:
            raise RuntimeError("写 %s @%d 失败: %s" % (remote, off, r))
        off += len(piece)
        if off - last_report >= max(chunk * 30, 6000) or off >= total:
            print("    %s: %d/%d" % (remote, off, total))
            last_report = off

    r = exec_raw(s, "f.close()\nimport os\nprint('SZ',os.stat(%r)[6])\n" % remote)
    sz = None
    for t in r.replace("'", ' ').replace(',', ' ').split():
        if t.isdigit():
            sz = int(t)
    if sz != total:
        raise RuntimeError("大小不符 期望%d 实得%s (%s)" % (total, sz, r.strip()))
    print("    -> %s OK (%d bytes)" % (remote, total))


def main():
    files = list(FILES)
    if '--no-font' in sys.argv:
        files = [f for f in files if 'bmf' not in f[0]]
    print("端口:", PORT)
    for lo, rm in files:
        print("   ", lo, "->", rm)
    s = open_and_halt(PORT)
    print("已打断 main.py")
    try:
        for local_rel, remote in files:
            print(">>> 上传 %s" % local_rel)
            upload(s, local_rel, remote)
        print("==== 全部上传完成 ====")
        r = exec_raw(s,
            "import os\n"
            "print('lib:',os.listdir('/lib'))\n"
            "print('font:',os.listdir('/font'))\n"
            "print('main:',os.stat('/main.py')[6],'bytes')\n")
        print(r.strip())
    finally:
        s.close()


if __name__ == '__main__':
    main()
