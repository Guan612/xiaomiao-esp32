# 不变量配置（SSID/密码已移到配网页，不再写死在这里）。
#
# WiFi SSID/密码：开机时由 lib/wifi_manager.py 从板子的 /wifi.json 读取。
# 首次使用 / 换 WiFi：连 "XiaoMiao-Setup" 热点 → 配网页输入即可（见 README）。

# NTP 服务器（国内可达）
NTP_HOST = "ntp.aliyun.com"
# 时区：东八区 UTC+8。格式 (UTC偏移秒, 夏令时秒)
TIMEZONE = (8 * 3600, 0)

# 天气：留空则用 IP 自动定位城市；填英文名更准（如 "Beijing"）
WEATHER_CITY = ""
# 天气刷新间隔（秒）。wttr.in 免费服务建议 >= 600
WEATHER_INTERVAL = 600
