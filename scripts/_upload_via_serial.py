"""通过 pyserial 直接操作 ESP32 raw REPL，绕过 mpremote 握手问题。

背景：main.py 开机自启，while 循环占住串口，mpremote 进不去 raw REPL。
本脚本先发 Ctrl-C 打断 main.py，进 raw REPL，再执行代码或上传二进制文件。

用法：
  # 执行任意 python（从 stdin）
  printf 'import os\nprint(os.listdir("/"))' | uv run python scripts/_upload_via_serial.py --port COM10

  # 上传二进制/文本文件
  uv run python scripts/_upload_via_serial.py --port COM10 upload 本地路径 :/板子路径
  uv run python scripts/_upload_via_serial.py upload 本地路径 :/板子路径 COM10  # 兼容旧用法
"""
import argparse
import base64
import os
import serial
import sys
import time

DEFAULT_PORT = os.environ.get("ESP32_PORT", "COM3")


def open_and_halt(port=DEFAULT_PORT):
    # 保持 pyserial 默认 DTR/RTS 电平；COM10 这类板子强行拉低会持续复位。
    s = serial.Serial(port, 115200, timeout=1)
    # 开串口会让部分板子复位，必须在 boot 后 main.py 启动前持续打断。
    end = time.time() + 8.0
    while time.time() < end:
        s.write(b'\x03')
        time.sleep(0.15)
        s.read(512)
    # 排空打断后的残留
    end = time.time() + 1.0
    while time.time() < end:
        if not s.read(256):
            break
        time.sleep(0.05)
    return s


def to_raw_repl(s):
    s.write(b'\x01')  # Ctrl-A
    time.sleep(0.4)
    r = s.read(512) or b''
    if b'raw REPL' not in r:
        raise RuntimeError("进 raw REPL 失败: %r" % r[-80:])


def to_friendly(s):
    s.write(b'\x02')  # Ctrl-B
    time.sleep(0.15)
    s.read(256)


def exec_raw(s, code):
    """在 raw REPL 执行一段代码，返回输出。

    假定已在 raw REPL（调用方负责进入并保持）。每次发 Ctrl-B+Ctrl-A 重新进入
    干净的 raw 状态，清掉上一次 exec 的残留（如语法错误会卡在 '>' 提示）。
    """
    if isinstance(code, str):
        code = code.encode('utf-8')
    # Ctrl-B 回 friendly，再 Ctrl-A 进 raw，得到干净的 'raw REPL; ...>' 状态
    s.write(b'\x02')
    time.sleep(0.1)
    s.read(256)
    s.write(b'\x01')
    time.sleep(0.3)
    r = s.read(256) or b''
    if b'raw REPL' not in r and b'>' not in r:
        raise RuntimeError("进 raw REPL 失败: %r" % r[-80:])
    s.write(code)
    s.write(b'\x04')  # Ctrl-D 执行
    time.sleep(0.2)
    out = b''
    end = time.time() + 6
    while time.time() < end:
        chunk = s.read(512)
        if chunk:
            out += chunk
            # raw REPL: 执行后输出形如 b'...stdout...\r\n\x04...stderr...\r\n\x04>'
            if out.endswith(b'\x04>'):
                break
        else:
            time.sleep(0.03)
    # 去掉协议标记，保留真实输出
    text = out.decode('utf-8', 'replace')
    if '\x04' in text:
        # 第一个 \x04 之前是 stdout，之后是 stderr
        stdout, _, stderr = text.partition('\x04')
        stderr = stderr.replace('\x04>', '').strip()
        if stderr:
            return stdout + "\n[stderr] " + stderr
        return stdout
    return text


def upload_file(port, local, remote, chunk=300, batch=4):
    """以 base64 分块上传二进制文件到板子。

    全程保持单次串口连接 + raw REPL 会话，句柄 f 跨 exec_raw 保持。
    """
    if remote.startswith(":/"):
        remote = remote[1:]
    with open(local, 'rb') as f:
        data = f.read()
    s = open_and_halt(port)
    try:
        # 先确保父目录存在（remote 形如 /font/xxx）
        parent = remote.rsplit('/', 1)[0]
        if parent:
            mkdir_code = (
                "import os\n"
                "p=%r\n"
                "try:\n"
                "    os.mkdir(p)\n"
                "except OSError:\n"
                "    pass\n"
                "print('parent',p,'ok')\n"
            ) % parent
            r = exec_raw(s, mkdir_code)
            if 'Traceback' in r:
                print("建目录失败:", r)
                return False

        # 打开目标 + 导入解码模块（变量 f、B 在 raw REPL 会话中保持）
        code = (
            "f=open(%r,'wb')\n"
            "import ubinascii as B\n"
            "D=getattr(B,'a2b_base64',None) or B.b64decode\n"
            "print('opened')\n"
        ) % remote
        r = exec_raw(s, code)
        if 'Traceback' in r or 'opened' not in r:
            print("打开目标文件失败:", r)
            return False

        total = len(data)
        i = 0
        while i < total:
            lines = []
            start = i
            for _ in range(batch):
                if i >= total:
                    break
                piece = data[i:i + chunk]
                b64 = base64.b64encode(piece).decode('ascii')
                lines.append("f.write(D(%r))" % b64)
                i += len(piece)
            r = exec_raw(s, "\n".join(lines) + "\n")
            if "Traceback" in r:
                print("写入失败 @%d: %s" % (start, r))
                return False
            if i % (chunk * batch * 5) == 0 or i >= total:
                print("  已传 %d / %d" % (min(i, total), total))
        rc = exec_raw(s, "f.close()\nimport os\nprint('done size',os.stat(%r)[6])\n" % remote)
        print(rc.strip())
        return True
    finally:
        to_friendly(s)
        s.close()


def main():
    parser = argparse.ArgumentParser(description="通过 ESP32 raw REPL 执行代码或上传文件")
    parser.add_argument("--port", default=DEFAULT_PORT, help="串口号，默认读取 ESP32_PORT 或 COM3")
    parser.add_argument("command", nargs="?", help="upload 表示上传文件；省略则执行 stdin 代码")
    parser.add_argument("args", nargs="*")
    ns = parser.parse_args()

    if ns.command == 'upload':
        if len(ns.args) < 2:
            parser.error("upload 需要: 本地路径 :/板子路径 [端口]")
        local, remote = ns.args[0], ns.args[1]
        port = ns.args[2] if len(ns.args) > 2 else ns.port
        ok = upload_file(port, local, remote)
        sys.exit(0 if ok else 1)
    else:
        code = sys.stdin.read()
        s = open_and_halt(ns.port)
        try:
            print(exec_raw(s, code))
        finally:
            to_friendly(s)
            s.close()


if __name__ == '__main__':
    main()
