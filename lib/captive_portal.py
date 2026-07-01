"""AP 配网（Captive Portal）—— 纯 socket 手写，零外部依赖。

⚠️ 重要：配网期间【不开启 STA】（不做 WiFi 扫描）。
实测在这块 ESP32 上，AP + STA 同时 active 会导致 AP 网络栈收不到包，
80 端口打不开。所以本模块只开 AP，用户在浏览器访问 192.168.4.1，
手动输入 WiFi 名 + 密码，保存后重启，由 wifi_manager 用 STA 连接。

工作原理：
  1. 开放热点 "Xueersi-Setup"（无密码，IP 固定 192.168.4.1）
  2. HTTP 服务（select 轮询 TCP/80）：
       GET  /    → 返回统一控制台（含配网表单）
       POST /wifi → 追加/更新 /wifi.json → 返回"已保存，重启中"页 → 重启
       POST /action → 刷写模式 / 重启

入口：run(disp=None) —— 阻塞直到配网完成并重启。
"""
import socket
import time
import network
import json
import uselect
import machine
import webui as webui_mod

# ---- 配网常量 ----
AP_SSID = "Xueersi-Setup"
AP_IP = "192.168.4.1"
WIFI_FILE = "/wifi.json"
# 中文字库（与 astronaut_watch.py 共用；缺失时屏幕提示回退英文）
FONT_FILE = "/font/noto_sans_sc_16px_gb2312.v3.bmf"

# captive portal 检测端点（各平台探测路径，统一返回配网页）
# iOS/macOS: /hotspot-detect.html ; Android: /generate_204 ; Windows: /ncsi.txt
CAPTIVE_PATHS = {"/", "/hotspot-detect.html", "/generate_204", "/ncsi.txt"}


def start_ap():
    """开启开放热点（不激活 STA）。返回 AP WLAN 对象。

    关键：必须关闭 STA，否则 AP+STA 同开会让 AP 收不到包。
    """
    # 先关 STA，确保 AP 单独工作
    sta = network.WLAN(network.STA_IF)
    if sta.active():
        sta.active(False)
        time.sleep(0.3)

    ap = network.WLAN(network.AP_IF)
    ap.active(True)
    ap.config(essid=AP_SSID, authmode=network.AUTH_OPEN)
    ap.ifconfig((AP_IP, "255.255.255.0", AP_IP, AP_IP))
    for _ in range(20):
        if ap.active():
            break
        time.sleep(0.1)
    return ap


# ---- HTTP 响应封装 ----
def _http_response(status, body, content_type="text/html", extra_headers=""):
    head = (
        "HTTP/1.1 %s\r\n"
        "Content-Type: %s\r\n"
        "Content-Length: %d\r\n"
        "Connection: close\r\n"
        "%s\r\n"
    ) % (status, content_type, len(body), extra_headers)
    return head.encode() + body


def _render_setup_page():
    """渲染统一控制台配网页。"""
    return webui_mod.render_setup_page(AP_SSID, AP_IP)


def _render_done_page():
    return webui_mod.render_done(
        "已保存",
        "板子正在重启并连接 WiFi。断开 XiaoMiao-Setup 热点，等待太空人界面出现。",
    )


def _parse_form(body):
    """解析 application/x-www-form-urlencoded，返回 dict。body 可为 bytes/str。"""
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


def _urldecode(s):
    """URL 解码（+ 转空格，%XX 转字节）。"""
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


def _load_saved_creds():
    """读取已保存 WiFi。"""
    try:
        with open(WIFI_FILE, "r") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []

    creds = []
    seen = set()
    for item in data.get("networks", []):
        item_ssid = item.get("ssid", "").strip()
        item_password = item.get("password", "")
        if item_ssid and item_ssid not in seen:
            creds.append({"ssid": item_ssid, "password": item_password})
            seen.add(item_ssid)

    return creds


def _save_creds(ssid, password):
    """追加/更新 WiFi 凭据到 /wifi.json。"""
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


def run(disp=None):
    """开 AP + HTTP，阻塞直到配网完成(重启)。

    不开 STA（扫描）—— AP 单独工作才稳定，详见模块顶部说明。
    """
    ap = start_ap()
    print("[portal] AP up:", AP_SSID, "ip:", ap.ifconfig()[0])

    # 屏幕提示（中文走字库，字库缺失则回退英文）
    easydisp = None
    if disp is not None:
        try:
            import easydisplay as ed
            easydisp = ed.EasyDisplay(disp, "RGB565",
                                      font=FONT_FILE)
        except Exception as e:
            print("[portal] 字体加载失败，回退英文:", e)

        disp.fill(0)
        disp.fill_rect(0, 0, 160, 16, 0xF800)  # 红色状态栏
        if easydisp:
            easydisp.text("WiFi 配网", 2, 0, 0xFFFF, show=False)
            easydisp.text("请连接热点:", 2, 22, 0xFFFF, show=False)
            easydisp.text(AP_SSID, 2, 40, 0x07FF, show=False)
            easydisp.text("浏览器打开:", 2, 62, 0xFFFF, show=False)
            easydisp.text(AP_IP, 2, 80, 0x07E0, show=False)
        else:
            disp.text("WiFi Setup", 2, 2, 0xFFFF)
            disp.text("Connect to:", 2, 22, 0xFFFF)
            disp.text(AP_SSID, 2, 36, 0x07FF)
            disp.text("Open browser:", 2, 56, 0xFFFF)
            disp.text(AP_IP, 2, 70, 0x07E0)
        disp.show()

    # ---- HTTP socket（TCP/80）----
    srv_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv_sock.bind(("0.0.0.0", 80))
    srv_sock.listen(3)
    srv_sock.setblocking(False)

    poller = uselect.poll()
    poller.register(srv_sock, uselect.POLLIN)

    print("[portal] HTTP listening on 80")
    while True:
        try:
            events = poller.poll(200)  # 200ms 超时
            for sock, _ev in events:
                if sock == srv_sock:
                    action = http_handle(srv_sock)
                    if action == "flash":
                        return "flash"
        except OSError:
            pass
        time.sleep(0.005)


class CaptivePortalUI:
    """离线运行时 AP 控制后台。

    与 run() 不同，这个类不阻塞主程序；主循环定期 poll()，本地工具还能继续用。
    """

    def __init__(self):
        self.ap = start_ap()
        print("[portal] AP up:", AP_SSID, "ip:", self.ap.ifconfig()[0])
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind(("0.0.0.0", 80))
        self._srv.listen(3)
        self._srv.setblocking(False)
        self._poller = uselect.poll()
        self._poller.register(self._srv, uselect.POLLIN)
        print("[portal] HTTP listening on 80")

    def poll(self, timeout_ms=500):
        action = None
        try:
            events = self._poller.poll(timeout_ms)
            for sock, _ev in events:
                if sock == self._srv:
                    action = http_handle(self._srv)
        except OSError:
            pass
        return action


def _read_request(conn):
    """读取完整 HTTP 请求，返回 (method, path, body) 或 None。

    先读出 header 段（\r\n\r\n 之前），按 Content-Length 继续读完整 body，
    避免 POST body 被截断（手机表单常分多包发送）。
    """
    chunks = []
    total = 0
    deadline = time.ticks_add(time.ticks_ms(), 3000)  # 3s 超时
    # 第一阶段：读到 \r\n\r\n（header 结束）
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
        return None  # 没收到完整 header
    head_text = header[:sep].decode("latin-1")
    body = header[sep + 4:]  # header 之后已经收到的 body

    # 解析 Content-Length，继续读剩余 body
    clen = 0
    for line in head_text.split("\r\n"):
        low = line.lower()
        if low.startswith("content-length:"):
            try:
                clen = int(low.split(":", 1)[1].strip())
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

    # 解析请求行
    first_line = head_text.split("\r\n", 1)[0]
    parts = first_line.split(" ")
    if len(parts) < 2:
        return None
    method = parts[0]
    path = parts[1].split("?", 1)[0]
    return method, path, body


def http_handle(srv_sock):
    """非阻塞处理一次 HTTP 请求（accept + 读取完整请求 + 响应）。"""
    try:
        conn, _ = srv_sock.accept()
    except OSError:
        return
    conn.settimeout(1.5)  # 足够等 POST body 到达
    try:
        parsed = _read_request(conn)
        if not parsed:
            conn.close()
            return None
        method, path, body = parsed

        if method == "GET":
            # 所有路径都返回配网页（含 captive 检测路径）
            resp = _http_response("200 OK", _render_setup_page().encode())
        elif method == "POST":
            resp = _handle_post(path, body)
        else:
            resp = _http_response("405 Method Not Allowed", b"<h1>405</h1>")

        conn.send(resp)
        # 保存请求发完响应后重启
        if method == "POST" and path in ("/wifi", "/save"):
            time.sleep(0.5)
            conn.close()
            machine.reset()
        if method == "POST" and path == "/action":
            action = webui_mod.parse_form(body).get("cmd", "")
            if action == "reboot":
                time.sleep(0.5)
                conn.close()
                machine.reset()
            if action == "flash":
                return "flash"
        if method == "POST" and path == "/wifi-action":
            form = webui_mod.parse_form(body)
            if form.get("cmd") == "prefer":
                time.sleep(0.5)
                conn.close()
                machine.reset()
    except OSError:
        pass
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return None


def _handle_post(path, body):
    """处理 POST 请求。"""
    print("[portal] POST", path, "body_len:", len(body))
    if path in ("/wifi", "/save"):
        form = webui_mod.parse_form(body)
        ssid = form.get("ssid", "").strip()
        password = form.get("password", "")
        print("[portal] parsed ssid=%r" % ssid)
        if not ssid:
            return _http_response(
                "400 Bad Request",
                ('<html><body><h2>SSID 不能为空</h2>'
                 '<a href="/">返回重试</a></body></html>').encode(),
            )
        _save_creds(ssid, password)
        return _http_response("200 OK", _render_done_page().encode())
    if path == "/action":
        form = webui_mod.parse_form(body)
        cmd = form.get("cmd", "")
        if cmd == "flash":
            return _http_response(
                "200 OK",
                webui_mod.render_done(
                    "进入刷写模式",
                    "屏幕将提示 USB 上传就绪。",
                ).encode(),
            )
        if cmd == "reboot":
            return _http_response(
                "200 OK",
                webui_mod.render_done("正在重启", "板子正在重启。").encode(),
            )
        return _http_response(
            "400 Bad Request",
            webui_mod.render_done("操作不可用", "AP 配网模式只支持刷写和重启。").encode(),
        )
    if path == "/wifi-action":
        form = webui_mod.parse_form(body)
        cmd = form.get("cmd", "")
        ssid = form.get("ssid", "").strip()
        if cmd == "prefer" and ssid:
            if webui_mod.prefer_wifi(ssid):
                return _http_response(
                    "200 OK",
                    webui_mod.render_done(
                        "正在切换 WiFi",
                        "已设为首选 WiFi，板子正在重启并尝试连接。",
                    ).encode(),
                )
            return _http_response(
                "404 Not Found",
                webui_mod.render_done("切换失败", "找不到这个 WiFi。").encode(),
            )
        if cmd == "delete" and ssid:
            webui_mod.delete_wifi(ssid)
            return _http_response(
                "200 OK",
                webui_mod.render_done("WiFi 已删除", "已删除保存的 WiFi。").encode(),
            )
        return _http_response(
            "400 Bad Request",
            webui_mod.render_done("操作失败", "WiFi 操作无效。").encode(),
        )
    return _http_response("404 Not Found", b"<h1>404</h1>")
