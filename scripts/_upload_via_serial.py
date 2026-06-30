"""通过 pyserial 直接操作 ESP32 raw REPL，绕过 mpremote 握手问题。

背景：main.py 开机自启，while 循环占住串口，mpremote 进不去 raw REPL。
本脚本先发 Ctrl-C 打断 main.py，进 raw REPL，再执行代码或上传二进制文件。

用法：
  # 执行任意 python（从 stdin）
  printf 'import os\nprint(os.listdir("/"))' | uv run python scripts/_upload_via_serial.py

  # 上传二进制/文本文件
  uv run python scripts/_upload_via_serial.py upload 本地路径 :/板子路径 [端口]
"""
import serial
import sys
import time
import base64


def open_and_halt(port='COM3'):
    # dsrdtr/rtscts=False 尽量避免 DTR/RTS 电平变化触发 ESP32 复位。
    # 注意：本板关闭串口仍可能触发复位，故所有操作应在单次 open/close 内完成。
    s = serial.Serial(port, 115200, timeout=1, dsrdtr=False, rtscts=False)
    s.dtr = False
    s.rts = False
    time.sleep(0.5)
    # 排空开串口后板子吐出的 boot / main.py 日志
    end = time.time() + 0.8
    while time.time() < end:
        if not s.read(256):
            break
        time.sleep(0.05)
    # 多次 Ctrl-C 确保 main.py 被打断（落在启动/WiFi 连接期间也能打断）
    for _ in range(4):
        s.write(b'\x03')
        time.sleep(0.4)
    time.sleep(0.6)
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


def upload_file(port, local, remote, chunk=400):
    """以 base64 分块上传二进制文件到板子。

    全程保持单次串口连接 + raw REPL 会话，句柄 f 跨 exec_raw 保持。
    """
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
            "print('opened')\n"
        ) % remote
        r = exec_raw(s, code)
        if 'Traceback' in r or 'opened' not in r:
            print("打开目标文件失败:", r)
            return False

        total = len(data)
        i = 0
        while i < total:
            piece = data[i:i + chunk]
            b64 = base64.b64encode(piece).decode('ascii')
            wcode = "f.write(B.b64decode(%r))\n" % b64
            r = exec_raw(s, wcode)
            if "Traceback" in r:
                print("写入失败 @%d: %s" % (i, r))
                return False
            i += chunk
            if i % (chunk * 20) == 0 or i >= total:
                print("  已传 %d / %d" % (min(i, total), total))
        rc = exec_raw(s, "f.close()\nimport os\nprint('done size',os.stat(%r)[6])\n" % remote)
        print(rc.strip())
        return True
    finally:
        to_friendly(s)
        s.close()


def main():
    args = sys.argv[1:]
    if args and args[0] == 'upload':
        local, remote = args[1], args[2]
        port = args[3] if len(args) > 3 else 'COM3'
        ok = upload_file(port, local, remote)
        sys.exit(0 if ok else 1)
    else:
        code = sys.stdin.read()
        s = open_and_halt()
        try:
            print(exec_raw(s, code))
        finally:
            to_friendly(s)
            s.close()


if __name__ == '__main__':
    main()
