# esp32-xiaomiao

学而思小喵掌机 (XiaoMiao) 本地开发项目。

硬件是标准 **ESP32-D0WD-V3**（4MB Flash + PSRAM），不依赖学而思专有环境，
完全可用开源工具链（MicroPython + esptool + mpremote）自行开发、刷固件、跑程序。
**就算后台停服，板子本身照常开发运行。**

## 环境

- Python 3.12（uv 管理，见 `.python-version`）
- 依赖：`esptool`（烧录）、`mpremote`（上传/REPL）—— 见 `pyproject.toml`

```bash
uv sync          # 安装依赖到 .venv（项目已配置好，直接用）
```

## 目录

```
esp32/
├── pyproject.toml         # uv 项目（esptool + mpremote）
├── upstream/              # 上游仓库 xueersi-xiaomiao（含固件+示例）
│   └── bins/              # ★ 两个现成 MicroPython 固件
├── firmware/              # 你自己的固件 bin 放这里
├── lib/
│   ├── st7735_buf.py      # ST7735 framebuffer 驱动（已从 upstream 拷出）
│   ├── bigfont.py         # 大号像素字体 + 太空人绘制（程序化，无外部资源）
│   ├── weather.py         # 天气获取(wttr.in 免key) + 天气图标
│   ├── wifi_manager.py    # WiFi 凭证管理（读 /wifi.json）+ 连接调度
│   └── captive_portal.py  # AP 配网（开热点 + DNS 劫持 + HTTP 配网页）
├── font/
│   └── *.bmf              # 16px 中文字库
├── apps/                  # 上传到板子运行的脚本
│   ├── hello.py           # 蜂鸣器 + 按键（不依赖屏幕驱动）
│   ├── hello_screen.py    # ★ 点亮屏幕 demo（自包含）
│   ├── wifi_config.py     # WiFi/NTP/天气 凭据（**改成你的**）
│   └── astronaut_watch.py # ★ WiFi 太空人手表（NTP对时 + 天气）
├── src/xiaomiao.py        # 引脚常量
├── scripts/flash.py       # erase / 刷固件 / 上传 / REPL 封装
└── docs/
```

## 两条开发路线

| 路线 | 固件 | 特点 | 适合 |
|------|------|------|------|
| **A. Framebuffer**（推荐入门） | `upstream/bins/ESP32_SPIRAM_1.24_SDCARDST7735.bin` | 标准 MicroPython + st7735_buf.py 驱动，用 `framebuf` 画图 | 简单 UI、游戏、学习 |
| **B. LVGL** | `upstream/bins/lvgl9.3_mpy_*.bin` | 带 LVGL 9.3 图形库，组件丰富但 API 复杂 | 复杂界面、表盘类应用 |

> 官方纯 MicroPython（micropython.org）**没有屏幕驱动**，需走上面 A 或 B。

## 快速上手

### 1. 接板子、确认端口
USB 连接后，在「设备管理器 → 端口」找到 CH340/CP2102 对应的 `COMx`：

```bash
set ESP32_PORT=COM5      # cmd（改成你的实际端口）
$env:ESP32_PORT="COM5"   # PowerShell
```

### 2. 擦除 + 刷固件（路线 A）
进入下载模式：**按住 BOOT，按一下 EN/RST，松开 BOOT**。

```bash
uv run python scripts/flash.py erase
uv run python scripts/flash.py framebuffer      # 一键刷 framebuffer 固件
# 或走 LVGL 路线：
# uv run python scripts/flash.py lvgl
```

### 3. 上传驱动 + 示例并运行
```bash
uv run python scripts/flash.py upload lib\st7735_buf.py        # 传屏幕驱动
uv run python scripts/flash.py upload apps\hello_screen.py :/main.py  # 设为开机自启

uv run python scripts/flash.py repl     # 进 REPL 观察 / 交互
```

复位即运行 `main.py`。屏幕应显示标题 + 三色块，按任意键蜂鸣器响。

## 🚀 太空人手表（WiFi 对时 + 天气）

屏幕显示像素风太空人 + 大号实时时间 + 日期 + **天气**(图标+温度+湿度+状况)。
连 WiFi 后 NTP 自动对时；天气页可手动刷新天气（免 key，按 IP 定位城市）。

**第一步：配置（首次用 AP 配网，见下方「AP 配网」）。**
复位后屏幕短暂显示 `A:WiFi setup`，这时按住/点按 `A` 才会开热点 `XiaoMiao-Setup`；
手机连上即弹配网页选 WiFi、输密码，
存盘重启后自动连接。NTP/天气等不变量配置仍在 `apps/wifi_config.py`（可选改）。

**第二步：部署：**

```bash
uv run python scripts/flash.py upload apps\wifi_config.py
uv run python scripts/flash.py upload apps\astronaut_watch.py :/main.py
uv run python scripts/flash.py upload lib\st7735_buf.py
uv run python scripts/flash.py upload lib\bigfont.py
uv run python scripts/flash.py upload lib\easydisplay.py
uv run python scripts/flash.py upload lib\watch_ui.py
uv run python scripts/flash.py upload lib\keynav.py
uv run python scripts/flash.py upload lib\astro_icon.py
uv run python scripts/flash.py upload lib\local_sensor.py
uv run python scripts/flash.py upload lib\weather.py
uv run python scripts/flash.py upload lib\online_center.py
uv run python scripts/flash.py upload lib\wifi_manager.py
uv run python scripts/flash.py upload lib\captive_portal.py
uv run python scripts/flash.py upload lib\webui.py
# 中文字库（务必传到板子 /font/ 目录，否则界面回退英文）：
uv run python scripts/flash.py upload font\noto_sans_sc_16px_gb2312.v3.bmf :/font/noto_sans_sc_16px_gb2312.v3.bmf
```

**第三步：** 按一下 EN 复位 → 需要配网时在 `A:WiFi setup` 提示期间按 `A` →
手机连 `XiaoMiao-Setup` 配网 → 重启后自动连 WiFi → 对时 → 显示太空人。
不按 `A` 会直接进入离线优先模式，本地页（如色子）照常可用。
天气页按 `A` 手动刷新天气。

**按键界面：**

- `右`：时钟 → 在线大全 → 天气 → 色子 → 时钟
- `左`：反向切换页面
- `上 / 下`：在线大全首页移动选择；在线详情滚动内容
- `A`：在线大全首页进入；在线详情刷新；天气页刷新天气；色子页掷骰
- `B`：在线详情返回在线大全首页；其他页面返回时钟页
- `长按 B`：直接返回时钟页

布局（160×128 横屏）：
```
┌──────────────────────────────┐
│ 在线 192.168.x.x     31°C   │ ← 状态栏(绿=在线/红=离线) + 右上温度
├──────┬───────────────────────┤
│      │  12:34 56  ← 时间(青)+秒(橙)同一行
│ 太空  │                       │
│ 人    │ 06-28 周六 ← 日期(黄)+星期(灰)
├──────┴───────────────────────┤
│ 🌧  28°C  52%                │ ← 天气图标 + 温度(黄) + 湿度(青)
│ 雨                           │ ← 状况文字(中文)
└──────────────────────────────┘
```

**天气数据源：** [wttr.in](https://wttr.in) — 免费、无需 API key。
- `WEATHER_CITY=""` 时按公网 IP 自动定位城市
- 填英文名（如 `"Beijing"`、`"Shanghai"`）定位更准
- 状况含晴/云/雨/雪/雷/雾，自动选对应像素图标

> WiFi 不通时会快速进入离线模式，同时自动开启 `Xueersi-Setup` 热点和
> `192.168.4.1` 控制台；本地工具仍可继续使用。
> NTP 每小时刷新；天气先在天气页按 `A` 手动刷新，已有天气数据后才会按 `WEATHER_INTERVAL` 自动刷新。

**Web 控制台：** 在线后浏览器打开屏幕上的 IP，可在同一个控制台里刷新天气/对时、
进入刷写模式、重启、添加/更新 WiFi，以及切换/删除已保存的 WiFi。
AP 配网页也复用这套控制台界面。

**在线大全数据源：** [UAPI 全网热榜](https://uapis.cn/docs/api-reference/get-misc-hotboard)
和 [yunapi.cn 网易云热评 API](https://yunapi.cn/api/sjwyyrp)。
在线大全需要联网，接口不可达时会提示获取失败。

## 📡 AP 配网（首次连接 WiFi）

不再需要把 WiFi 密码写死在代码里刷进板子。首次开机（或换 WiFi）时，复位后
在 `A:WiFi setup` 提示期间按 `A`，板子才会**自己开热点**；手机连上后
**自动弹出统一控制台**，选 WiFi、输密码即可；这个页面也提供刷写模式和重启入口。

**触发条件：** 启动提示期间按 `A`。这样没网络时不会阻塞本地工具使用。
可以记住多个 WiFi，比如家里和公司各配一次；开机会按保存记录依次尝试，连上后下次优先试这个。

### 使用步骤

1. **上传后按 EN 复位，并在 `A:WiFi setup` 提示期间按 `A`。** 屏幕显示红色 `WiFi Setup` 状态栏。
2. **手机连热点 `XiaoMiao-Setup`**（无密码）。iOS/Android/Windows 连上后
   会**自动弹出配网页**；没弹的话，浏览器随便输个网址（如 `xiao.com`）
   或直接访问 `192.168.4.1` 也会被劫持到配网页。
3. **输入 WiFi 名 → 输密码 → 保存。** 配过多个 WiFi 时会追加/更新到 `/wifi.json`。
4. **板子自动重启**，连上你选的 WiFi，正常显示太空人。

### 换 WiFi / 重置配网

配网凭据存在板子的 `/wifi.json`。新格式类似：

```json
{"networks":[{"ssid":"公司WiFi","password":"..."},{"ssid":"家里WiFi","password":"..."}]}
```

重新配网有两种方式：

- **启动时按 A 进配网：** 复位后在 `A:WiFi setup` 提示期间按 `A`。
- **手动删凭据（最干净）：** 进 REPL 删文件后复位——
  ```bash
  uv run python scripts/flash.py repl
  # REPL 里输入：
  >>> import os; os.remove('/wifi.json')
  >>> import machine; machine.reset()
  ```

> 配网模块：`lib/captive_portal.py`（热点 + DNS 劫持 + HTTP 配网页）、
> `lib/wifi_manager.py`（读 `/wifi.json` + 连接调度）。零外部依赖。

## 常用命令

```bash
uv run python scripts/flash.py                                  # 查看用法
uv run python scripts/flash.py erase                            # 擦除
uv run python scripts/flash.py firmware firmware\xxx.bin 0x0    # 刷自定义固件
uv run python scripts/flash.py upload apps\hello.py             # 上传脚本到 :/
uv run python scripts/flash.py repl                             # 进 REPL
```

## 引脚速查

| 部件 | 引脚 |
|------|------|
| 按键 上/下/左/右/A/B | 2 / 13 / 27 / 35 / 34 / 12 |
| TFT ST7735 (160x128) | SCK=18, MOSI=23, CS=5, DC=4, RES=19 |
| SD 卡 | SCK=18, MOSI=23, MISO=19, CS=22 |
| 蜂鸣器 | 14（PWM） |
| 光照 / 温度 | 36 / 39（ADC，仅输入） |
| I2C | SCL=15, SDA=21（电机/LED @ 0x40） |
| UART0 | TX=1, RX=3 |

> ⚠️ GPIO 34/35/36/39 只能输入；GPIO12（B 键）启动敏感；
> 18/23/19 被 TFT 和 SD 卡共享，靠 CS 分时复用。

详见 `src/xiaomiao.py`。

## 参考与致谢

- 硬件逆向项目：https://github.com/pysn2012/xueersi-xiaomiao （已 clone 到 `upstream/`）
- ST7735 驱动源自：https://github.com/funnygeeker/micropython-easydisplay （MIT）
- MicroPython：https://micropython.org/
