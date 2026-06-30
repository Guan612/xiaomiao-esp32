r"""对比测试：关掉 STA，只开 AP + HTTP，看 80 端口能否 accept。

如果这个版本手机能访问 192.168.4.1 看到 "STA-OFF-OK"，
说明是 STA+AP 同时 active 导致 AP 网络栈不稳定。
"""
import network
import socket
import uselect
import time

sta = network.WLAN(network.STA_IF)
sta.active(False)
time.sleep(0.5)
ap = network.WLAN(network.AP_IF)
ap.active(True)
ap.config(essid="Xueersi-Setup", authmode=network.AUTH_OPEN)
ap.ifconfig(("192.168.4.1", "255.255.255.0", "192.168.4.1", "192.168.4.1"))

print("STA off:", sta.active())
print("AP up:", ap.active(), ap.ifconfig()[0])

srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("0.0.0.0", 80))
srv.listen(3)
srv.setblocking(False)

p = uselect.poll()
p.register(srv, uselect.POLLIN)
print("listening on 80, waiting for requests...")

BODY = b"STA-OFF-OK: if you see this, AP+HTTP works without STA"
HEAD = b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\nConnection: close\r\n\r\n" % len(BODY)

got = 0
while True:
    for so, _ in p.poll(500):
        if so == srv:
            try:
                c, a = srv.accept()
                c.settimeout(2)
                r = c.recv(512)
                got += 1
                print("REQ", got, a, r.split(b"\r\n")[0])
                c.send(HEAD + BODY)
                c.close()
            except OSError as e:
                print("accept err", e)
