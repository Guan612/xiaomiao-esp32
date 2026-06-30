r"""最小化 AP + HTTP 测试，排查配网页打不开问题。

跑这个会覆盖 main.py 流程：开 AP → 开 HTTP（不做 scan、不做 DNS），
收到任何请求就回 "HELLO"。用来确认 80 端口对外可达。

部署：uv run python scripts/flash.py upload apps\test_portal.py :/main.py
复位后电脑/手机连 Xueersi-Setup，浏览器开 192.168.4.1 应看到 HELLO。
"""
import socket
import network

AP_SSID = "Xueersi-Setup"
AP_IP = "192.168.4.1"

ap = network.WLAN(network.AP_IF)
ap.active(True)
ap.config(essid=AP_SSID, authmode=network.AUTH_OPEN)
ap.ifconfig((AP_IP, "255.255.255.0", AP_IP, AP_IP))

sta = network.WLAN(network.STA_IF)
sta.active(False)  # 关掉 STA，排除 scan 干扰

srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("0.0.0.0", 80))
srv.listen(3)
print("[test] AP up:", AP_SSID, "HTTP on 80")

BODY = b"<h1>HELLO from ESP32</h1><p>If you see this, port 80 works.</p>"
HEAD = (b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\nConnection: close\r\n\r\n"
        % len(BODY))

n = 0
while True:
    try:
        conn, addr = srv.accept()
        conn.settimeout(2.0)
        req = conn.recv(512)
        n += 1
        print("[test] req #%d from %s: %s" % (n, addr, req.split(b'\r\n',1)[0]))
        conn.send(HEAD + BODY)
        conn.close()
    except OSError:
        pass
