"""WebUI 控制台 + 配网页共享组件。

这个模块既提供在线运行时控制台，也给 AP 配网页复用同一套 HTML/HTTP
小工具，避免配网 WebUI 和控制台长成两套系统。

运行时控制台（STA 模式，与主时钟循环共存）：

在已连 WiFi（STA 模式）运行期间，监听 80 端口。浏览器打开屏幕上显示的
IP（如 http://192.168.x.x）即可看到控制面板，支持：
  - 进入刷写模式（停网络/HTTP，电脑端 flash.py upload 走 raw REPL）
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
import json

PORT = 80
WIFI_FILE = "/wifi.json"


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


def http_response(status, body, content_type="text/html"):
    return _http_response(status, body, content_type)


def _button(label, value, cls):
    return '<button name="cmd" value="%s" class="%s">%s</button>' % (
        value, cls, label)


def _html_escape(s):
    s = str(s)
    return (s.replace("&", "&amp;").replace("<", "&lt;")
             .replace(">", "&gt;").replace('"', "&quot;"))


def _scan_wifi_ssids():
    try:
        import network
        wlan = network.WLAN(network.STA_IF)
        if not wlan.active():
            return []
        found = {}
        for ap in wlan.scan():
            raw = ap[0]
            try:
                ssid = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            except Exception:
                ssid = raw.decode("latin-1") if isinstance(raw, bytes) else raw
            ssid = ssid.strip()
            if ssid:
                rssi = ap[3] if len(ap) > 3 else -999
                if ssid not in found or rssi > found[ssid]:
                    found[ssid] = rssi
        ordered = sorted(found.items(), key=lambda item: item[1], reverse=True)
        return [ssid for ssid, _rssi in ordered[:8]]
    except Exception as e:
        print("[webui] wifi scan failed:", e)
        return []


def _render_scan_list(ssids):
    if not ssids:
        return '<div class="empty">没有扫到附近 WiFi，也可以手动输入</div>'
    items = []
    for ssid in ssids:
        safe = _html_escape(ssid)
        items.append("""<button type="button" class="wifi-pick"
onclick="document.getElementById('wifi-ssid').value='%s'">%s</button>""" %
                     (safe, safe))
    return '<div class="scan-list">%s</div>' % "".join(items)


def _render_wifi_form(title="添加 WiFi", button="保存并重启", scan=False):
    scan_html = ""
    if scan:
        scan_html = ("<label>附近 WiFi</label>" +
                     _render_scan_list(_scan_wifi_ssids()))
    else:
        scan_html = ('<a class="scan-link" href="/scan">扫描附近 WiFi</a>')
    return ("""<div class="card">
<h3>%s</h3>
<form method="POST" action="/wifi">
%s
<label>WiFi 名称 (SSID)</label>
<input id="wifi-ssid" name="ssid" placeholder="输入你的 WiFi 名" required>
<label>密码</label>
<input name="password" type="password" placeholder="WiFi 密码">
<button type="submit" class="b-primary">%s</button>
</form>
</div>""") % (title, scan_html, button)


def _render_wifi_manager(current_ssid=""):
    networks = _load_saved_creds()
    if not networks:
        return """<div class="card">
<h3>WiFi 管理</h3>
<div class="empty">还没有保存的 WiFi</div>
</div>"""
    rows = []
    for idx, item in enumerate(networks):
        ssid = item.get("ssid", "")
        safe_ssid = _html_escape(ssid)
        tags = []
        if idx == 0:
            tags.append("首选")
        if current_ssid and ssid == current_ssid:
            tags.append("当前")
        tag_html = (" <span class=\"tag\">%s</span>" % " / ".join(tags)) if tags else ""
        if current_ssid and ssid == current_ssid:
            primary = '<div class="wifi-state">正在使用</div>'
        elif idx == 0:
            primary = '<div class="wifi-state">已是首选</div>'
        else:
            primary = ("""<button name="cmd" value="prefer"
class="b-small b-primary">切换到这个 WiFi</button>""")
        rows.append("""<div class="wifi-row">
<div class="wifi-name">%s%s</div>
<form method="POST" action="/wifi-action">
<input type="hidden" name="ssid" value="%s">
%s
<button name="cmd" value="delete" class="b-small b-danger">删除</button>
</form>
</div>""" % (safe_ssid, tag_html, safe_ssid, primary))
    return """<div class="card">
<h3>WiFi 管理</h3>
%s
</div>""" % "\n".join(rows)


def _render_panel(info, show_wifi_form=True, scan_wifi=False):
    """渲染控制面板 HTML。info 为状态 dict（见 WebUI._status）。"""
    uptime_s = info["uptime"]
    up_h, rem = divmod(uptime_s, 3600)
    up_m, up_s = divmod(rem, 60)
    uptime = "%d:%02d:%02d" % (up_h, up_m, up_s)
    scan_script = (
        "<script>if(location.pathname=='/scan')history.replaceState(null,'','/');</script>"
        if scan_wifi else ""
    )
    return ("""<!DOCTYPE html><html><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>太空人手表 控制台</title>
<style>
body{font-family:-apple-system,sans-serif;background:#0d1b2a;color:#e0e1dd;
margin:0;padding:18px;max-width:480px;margin:0 auto}
h2{color:#48cae4;text-align:center;margin:8px 0}
.card,.stat{background:#1b263b;border-radius:10px;padding:14px;margin-top:10px;
font-size:14px;line-height:1.9}
.card h3{margin:0 0 8px;color:#48cae4;font-size:16px}
.wifi-row{border-top:1px solid #415a77;padding:10px 0}
.wifi-row:first-of-type{border-top:0}
.wifi-name{font-size:15px;margin-bottom:6px;word-break:break-all}
.wifi-state{color:#48cae4;font-weight:bold;margin:4px 0 8px}
.scan-list{display:block;margin-top:4px;max-height:160px;overflow-y:auto;
padding-right:2px}
.scan-link{display:block;text-align:center;background:#0d1b2a;color:#48cae4;
border:1px solid #415a77;border-radius:8px;padding:10px;text-decoration:none;
margin:6px 0 10px}
.wifi-pick{background:#0d1b2a;color:#e0e1dd;border:1px solid #415a77;
text-align:left;font-weight:normal;padding:10px;margin-top:6px}
.tag{color:#48cae4;font-size:12px}
.empty{color:#778da9}
.stat .k{color:#778da9}
.stat .v{color:#e0e1dd;float:right}
label{display:block;color:#778da9;font-size:13px;margin:10px 0 4px}
input{width:100%%;box-sizing:border-box;padding:12px;border-radius:8px;
border:1px solid #415a77;background:#0d1b2a;color:#e0e1dd;font-size:15px}
button{width:100%%;padding:14px;margin-top:10px;border:none;border-radius:8px;
font-size:15px;font-weight:bold}
.b-small{padding:10px;margin-top:6px}
.b-primary{background:#48cae4;color:#0d1b2a}
.b-danger{background:#e76f51;color:#fff}
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
%s
%s
<div class="card">
<h3>控制</h3>
<form method="POST" action="/action">
%s
</form>
</div>
<div class="hint">刷写模式：进入后会停网络和控制台，电脑上执行<br>
<code>uv run python scripts/flash.py upload &lt;文件&gt;</code> 即可</div>
%s
</body></html>""") % (
        info["ip"], info["ssid"], info["time"], info["weather"],
        uptime, info["mem_free"] // 1024,
        _render_wifi_manager(info.get("ssid", "")) if show_wifi_form else "",
        _render_wifi_form("添加 WiFi", "保存 WiFi 并重启", scan=scan_wifi)
        if show_wifi_form else "",
        _button("🌤️ 立即刷新天气 &amp; 对时", "resync", "b-resync") +
        _button("🔌 进入刷写模式（raw REPL 上传）", "flash", "b-flash") +
        _button("📡 进入 AP 配网", "rewifi", "b-rewifi") +
        _button("🔄 重启板子", "reboot", "b-reboot"),
        scan_script,
    )


def render_setup_page(ap_ssid="Xueersi-Setup", ap_ip="192.168.4.1"):
    return ("""<!DOCTYPE html><html><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>XiaoMiao 控制台</title>
<style>
body{font-family:-apple-system,sans-serif;background:#0d1b2a;color:#e0e1dd;
margin:0;padding:18px;max-width:480px;margin:0 auto}
h2{color:#48cae4;text-align:center;margin:8px 0}
.card{background:#1b263b;border-radius:10px;padding:14px;margin-top:10px;
font-size:14px;line-height:1.8}
.card h3{margin:0 0 8px;color:#48cae4;font-size:16px}
.wifi-row{border-top:1px solid #415a77;padding:10px 0}
.wifi-row:first-of-type{border-top:0}
.wifi-name{font-size:15px;margin-bottom:6px;word-break:break-all}
.wifi-state{color:#48cae4;font-weight:bold;margin:4px 0 8px}
.scan-list{display:block;margin-top:4px;max-height:160px;overflow-y:auto;
padding-right:2px}
.scan-link{display:block;text-align:center;background:#0d1b2a;color:#48cae4;
border:1px solid #415a77;border-radius:8px;padding:10px;text-decoration:none;
margin:6px 0 10px}
.wifi-pick{background:#0d1b2a;color:#e0e1dd;border:1px solid #415a77;
text-align:left;font-weight:normal;padding:10px;margin-top:6px}
.tag{color:#48cae4;font-size:12px}
.empty{color:#778da9}
label{display:block;color:#778da9;font-size:13px;margin:10px 0 4px}
input{width:100%%;box-sizing:border-box;padding:12px;border-radius:8px;
border:1px solid #415a77;background:#0d1b2a;color:#e0e1dd;font-size:15px}
button{width:100%%;padding:14px;margin-top:10px;border:none;border-radius:8px;
font-size:15px;font-weight:bold}
.b-small{padding:10px;margin-top:6px}
.b-primary{background:#48cae4;color:#0d1b2a}
.b-danger{background:#e76f51;color:#fff}
.b-flash{background:#f4a261;color:#1b263b}
.b-reboot{background:#e76f51;color:#fff}
.hint{color:#778da9;font-size:12px;text-align:center;margin-top:10px;line-height:1.6}
</style></head><body>
<h2>🚀 XiaoMiao 控制台</h2>
<div class="card">
<h3>AP 配网</h3>
<div>热点：%s<br>地址：%s</div>
</div>
%s
%s
<div class="card">
<h3>维护</h3>
<form method="POST" action="/action">
%s
</form>
</div>
<div class="hint">保存后板子会重启并尝试连接 WiFi</div>
</body></html>""") % (
        ap_ssid, ap_ip,
        _render_wifi_manager(""),
        _render_wifi_form("连接 WiFi", "保存并连接"),
        _button("🔌 进入刷写模式", "flash", "b-flash") +
        _button("🔄 重启板子", "reboot", "b-reboot"),
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


def render_done(title, msg):
    return _render_done(title, msg)


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


def read_request(conn):
    return _read_request(conn)


def _urldecode(s):
    s = s.replace("+", " ")
    out = bytearray()
    i = 0
    b = s.encode("latin-1")
    while i < len(b):
        c = b[i]
        if c == 0x25 and i + 2 < len(b):  # '%'
            out.append(int(b[i + 1:i + 3], 16))
            i += 3
        else:
            out.append(c)
            i += 1
    try:
        return out.decode("utf-8")
    except Exception:
        return out.decode("latin-1")


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
        form[_urldecode(k)] = _urldecode(v)
    return form


def parse_form(body):
    return _parse_form(body)


def _load_saved_creds():
    try:
        with open(WIFI_FILE, "r") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    creds = []
    seen = set()
    for item in data.get("networks", []):
        ssid = item.get("ssid", "").strip()
        password = item.get("password", "")
        if ssid and ssid not in seen:
            creds.append({"ssid": ssid, "password": password})
            seen.add(ssid)
    return creds


def save_wifi_creds(ssid, password):
    networks = _load_saved_creds()
    updated = False
    for item in networks:
        if item.get("ssid") == ssid:
            item["password"] = password
            updated = True
            break
    if not updated:
        networks.insert(0, {"ssid": ssid, "password": password})
    with open(WIFI_FILE, "w") as f:
        json.dump({"networks": networks}, f)


def _save_networks(networks):
    cleaned = []
    seen = set()
    for item in networks:
        ssid = item.get("ssid", "").strip()
        if ssid and ssid not in seen:
            cleaned.append({"ssid": ssid, "password": item.get("password", "")})
            seen.add(ssid)
    with open(WIFI_FILE, "w") as f:
        json.dump({"networks": cleaned}, f)


def prefer_wifi(ssid):
    networks = _load_saved_creds()
    preferred = None
    rest = []
    for item in networks:
        if item.get("ssid") == ssid:
            preferred = item
        else:
            rest.append(item)
    if not preferred:
        return False
    _save_networks([preferred] + rest)
    return True


def delete_wifi(ssid):
    networks = [item for item in _load_saved_creds()
                if item.get("ssid") != ssid]
    _save_networks(networks)
    return True


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

    def close(self):
        """停止 HTTP 控制台，释放监听 socket。"""
        try:
            if self._poller and self._srv:
                self._poller.unregister(self._srv)
        except Exception:
            pass
        try:
            if self._srv:
                self._srv.close()
        except Exception:
            pass
        self._srv = None
        self._poller = None

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
                page = _render_panel(
                    self._status(),
                    show_wifi_form=True,
                    scan_wifi=(path == "/scan"),
                ).encode()
                conn.send(_http_response("200 OK", page))
            elif method == "POST" and path == "/action":
                form = _parse_form(body)
                cmd = form.get("cmd", "")
                action = cmd if cmd in ("flash", "reboot", "resync", "rewifi") else None
                # 先回响应，再让主循环执行动作
                msg = {
                    "flash": "已进入刷写模式。网络和控制台将关闭，请用 USB raw REPL 上传。",
                    "reboot": "板子正在重启…",
                    "resync": "正在刷新天气 &amp; 对时，稍后自动返回。",
                    "rewifi": "已清除 WiFi，板子重启后进入配网。",
                }.get(cmd, "未知操作")
                conn.send(_http_response("200 OK",
                            _render_done("操作已提交", msg).encode()))
            elif method == "POST" and path == "/wifi":
                form = _parse_form(body)
                ssid = form.get("ssid", "").strip()
                password = form.get("password", "")
                if ssid:
                    save_wifi_creds(ssid, password)
                    action = "reboot"
                    msg = "WiFi 已保存，板子正在重启并尝试连接。"
                    conn.send(_http_response("200 OK",
                                _render_done("WiFi 已保存", msg).encode()))
                else:
                    conn.send(_http_response("400 Bad Request",
                                _render_done("保存失败", "SSID 不能为空。").encode()))
            elif method == "POST" and path == "/wifi-action":
                form = _parse_form(body)
                cmd = form.get("cmd", "")
                ssid = form.get("ssid", "").strip()
                if cmd == "prefer" and ssid:
                    if prefer_wifi(ssid):
                        action = "reboot"
                        msg = "已设为首选 WiFi，板子正在重启并切换。"
                        conn.send(_http_response("200 OK",
                                    _render_done("正在切换 WiFi", msg).encode()))
                    else:
                        conn.send(_http_response("404 Not Found",
                                    _render_done("切换失败", "找不到这个 WiFi。").encode()))
                elif cmd == "delete" and ssid:
                    delete_wifi(ssid)
                    if ssid == self.ssid:
                        action = "reboot"
                        msg = "已删除当前 WiFi，板子正在重启。"
                    else:
                        msg = "已删除保存的 WiFi。"
                    conn.send(_http_response("200 OK",
                                _render_done("WiFi 已删除", msg).encode()))
                else:
                    conn.send(_http_response("400 Bad Request",
                                _render_done("操作失败", "WiFi 操作无效。").encode()))
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
