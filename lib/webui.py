"""WebUI 控制面板（运行时 HTTP 服务，与主时钟循环共存）。

在已连 WiFi（STA 模式）运行期间，监听 80 端口。浏览器打开屏幕上显示的
IP（如 http://192.168.x.x）即可看到控制面板，支持：
  - 进入刷写模式（停主循环，让 USB flash.py upload 能可靠打断）
  - 重启板子
  - 重新配网（删凭据 + 重启 → 回到 AP 配网流程）
  - 立即刷新天气 & 对时

设计：与 captive_portal.py 同款的非阻塞模式（socket + uselect.poll）。
主循环每帧调一次 poll(timeout_ms)：500ms 内有请求就处理，没有就返回 None。
返回动作字符串（None/"flash"/"reboot"/"resync"/"rewifi"）由主循环执行。

⚠️ 无鉴权，局域网内任意设备可访问（与配网页同级别，家用场景可接受）。
"""
import socket
import time
import uselect

PORT = 80


# ---- HTTP 响应封装（同 captive_portal）----
def _http_response(status, body, content_type="text/html"):
    head = (
        "HTTP/1.1 %s\r\n"
        "Content-Type: %s\r\n"
        "Content-Length: %d\r\n"
        "Connection: close\r\n"
        "\r\n"
    ) % (status, content_type, len(body))
    return head.encode() + body


def _render_panel(info):
    """渲染控制面板 HTML。info 为状态 dict（见 WebUI._status）。"""
    uptime_s = info["uptime"]
    up_h, rem = divmod(uptime_s, 3600)
    up_m, up_s = divmod(rem, 60)
    uptime = "%d:%02d:%02d" % (up_h, up_m, up_s)
    return ("""<!DOCTYPE html><html><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>太空人手表 控制台</title>
<style>
body{font-family:-apple-system,sans-serif;background:#0d1b2a;color:#e0e1dd;
margin:0;padding:20px;max-width:480px;margin:0 auto}
h2{color:#48cae4;text-align:center;margin:8px 0}
.stat{background:#1b263b;border-radius:10px;padding:14px;margin-top:10px;
font-size:14px;line-height:1.9}
.stat .k{color:#778da9}
.stat .v{color:#e0e1dd;float:right}
button{width:100%%;padding:15px;margin-top:10px;border:none;border-radius:10px;
font-size:15px;font-weight:bold}
.b-flash{background:#f4a261;color:#1b263b}
.b-resync{background:#48cae4;color:#0d1b2a}
.b-rewifi{background:#e9c46a;color:#1b263b}
.b-reboot{background:#e76f51;color:#fff}
.hint{color:#778da9;font-size:12px;text-align:center;margin-top:12px;line-height:1.6}
</style></head><body>
<h2>🛰️ 太空人手表 控制台</h2>
<div class="stat">
<span class="k">IP 地址</span><span class="v">%s</span><br>
<span class="k">WiFi</span><span class="v">%s</span><br>
<span class="k">当前时间</span><span class="v">%s</span><br>
<span class="k">天气</span><span class="v">%s</span><br>
<span class="k">已运行</span><span class="v">%s</span><br>
<span class="k">剩余内存</span><span class="v">%d KB</span>
</div>
<form method="POST" action="/action">
<button name="cmd" value="resync" class="b-resync">🌤️ 立即刷新天气 &amp; 对时</button>
<button name="cmd" value="flash" class="b-flash">🔌 进入刷写模式（停主程序，用 USB 上传）</button>
<button name="cmd" value="rewifi" class="b-rewifi">📡 重新配网（换 WiFi）</button>
<button name="cmd" value="reboot" class="b-reboot">🔄 重启板子</button>
</form>
<div class="hint">刷写模式：进入后屏幕提示就绪，电脑上执行<br>
<code>uv run python scripts/flash.py upload &lt;文件&gt;</code> 即可</div>
</body></html>""") % (
        info["ip"], info["ssid"], info["time"], info["weather"],
        uptime, info["mem_free"] // 1024,
    )


def _render_done(title, msg):
    return ("""<!DOCTYPE html><html><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>%s</title>
<style>body{font-family:-apple-system,sans-serif;background:#0d1b2a;color:#e0e1dd;
text-align:center;padding:60px 20px}
h2{color:#48cae4}p{color:#778da9;line-height:1.7}
a{color:#48cae4}</style></head><body>
<h2>%s</h2><p>%s</p>
<p><a href="/">返回控制台</a></p>
</body></html>""") % (title, title, msg)


def _read_request(conn):
    """读取完整 HTTP 请求，返回 (method, path, body) 或 None。同 captive_portal。"""
    deadline = time.ticks_add(time.ticks_ms(), 3000)
    header = b""
    while b"\r\n\r\n" not in header and time.ticks_ms() < deadline:
        try:
            d = conn.recv(1024)
        except OSError:
            break
        if not d:
            break
        header += d
    sep = header.find(b"\r\n\r\n")
    if sep < 0:
        return None
    head_text = header[:sep].decode("latin-1")
    body = header[sep + 4:]
    clen = 0
    for line in head_text.split("\r\n"):
        if line.lower().startswith("content-length:"):
            try:
                clen = int(line.split(":", 1)[1].strip())
            except ValueError:
                clen = 0
    while len(body) < clen and time.ticks_ms() < deadline:
        try:
            d = conn.recv(1024)
        except OSError:
            break
        if not d:
            break
        body += d
    first_line = head_text.split("\r\n", 1)[0]
    parts = first_line.split(" ")
    if len(parts) < 2:
        return None
    method = parts[0]
    path = parts[1].split("?", 1)[0]
    return method, path, body


def _parse_form(body):
    """解析 form，返回 dict。"""
    form = {}
    if not body:
        return form
    if isinstance(body, (bytes, bytearray)):
        try:
            body = body.decode("utf-8")
        except Exception:
            body = body.decode("latin-1")
    for pair in body.split("&"):
        if "=" in pair:
            k, v = pair.split("=", 1)
        else:
            k, v = pair, ""
        form[k.replace("+", " ")] = v.replace("+", " ")
    return form


class WebUI:
    """运行时控制面板 HTTP 服务。

    用法：
        web = WebUI(disp, easydisp)
        # 主循环里：
        action = web.poll(500)   # 最多等 timeout_ms；返回 None 或动作
    """

    def __init__(self, disp=None, easydisp=None):
        self.disp = disp
        self.easydisp = easydisp
        self.start_time = time.time()
        # 状态回调：主循环更新这些字段
        self.ip = ""
        self.ssid = ""
        self.weather = ""
        self._srv = None
        self._poller = None
        self._start()

    def _start(self):
        """建监听 socket + 注册 poller。"""
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind(("0.0.0.0", PORT))
        self._srv.listen(3)
        self._srv.setblocking(False)
        self._poller = uselect.poll()
        self._poller.register(self._srv, uselect.POLLIN)
        print("[webui] listening on :%d" % PORT)

    def set_state(self, ip="", ssid="", weather=""):
        """主循环调用，更新面板显示的状态。"""
        if ip:
            self.ip = ip
        if ssid:
            self.ssid = ssid
        if weather:
            self.weather = weather

    def _status(self):
        """构造面板状态 dict。"""
        import gc
        t = time.localtime()
        return {
            "ip": self.ip or "未知",
            "ssid": self.ssid or "未知",
            "time": "%02d:%02d:%02d" % (t[3], t[4], t[5]),
            "weather": self.weather or "无",
            "uptime": int(time.time() - self.start_time),
            "mem_free": gc.mem_free(),
        }

    def poll(self, timeout_ms=500):
        """主循环每帧调用：最多等 timeout_ms，处理一次 HTTP 请求。

        返回动作字符串：None / "flash" / "reboot" / "resync" / "rewifi"。
        """
        action = None
        try:
            events = self._poller.poll(timeout_ms)
            for _sock, _ev in events:
                action = self._handle()
        except OSError:
            pass
        return action

    def _handle(self):
        """处理一次连接，返回动作或 None。"""
        try:
            conn, _addr = self._srv.accept()
        except OSError:
            return None
        conn.settimeout(1.5)
        action = None
        try:
            parsed = _read_request(conn)
            if not parsed:
                return None
            method, path, body = parsed
            if method == "GET":
                page = _render_panel(self._status()).encode()
                conn.send(_http_response("200 OK", page))
            elif method == "POST" and path == "/action":
                form = _parse_form(body)
                cmd = form.get("cmd", "")
                action = cmd if cmd in ("flash", "reboot", "resync", "rewifi") else None
                # 先回响应，再让主循环执行动作
                msg = {
                    "flash": "已进入刷写模式。屏幕将提示就绪，请用 USB 上传文件。",
                    "reboot": "板子正在重启…",
                    "resync": "正在刷新天气 &amp; 对时，稍后自动返回。",
                    "rewifi": "已清除 WiFi，板子重启后进入配网。",
                }.get(cmd, "未知操作")
                conn.send(_http_response("200 OK",
                            _render_done("操作已提交", msg).encode()))
            else:
                conn.send(_http_response("404 Not Found", b"<h1>404</h1>"))
        except OSError:
            pass
        finally:
            try:
                conn.close()
            except Exception:
                pass
        return action
