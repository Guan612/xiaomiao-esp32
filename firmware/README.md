# firmware/

把 MicroPython 固件 (.bin) 放到这里。

## 从哪下

1. **官方 MicroPython**（推荐先用这个验证链路）
   https://micropython.org/download/ESP32_GENERIC/
   下载 `ESP32_GENERIC-*.bin`，改名后放本目录。

2. **带 LVGL 的 MicroPython**（仓库路线，支持图形 UI）
   来自 xueersi-xiaomiao 仓库的 `lvgl-mpy/` 或预编译 `bins/`。

## 烧录

```bash
# 完整固件（含 bootloader）通常烧到 0x0：
uv run python scripts/flash.py firmware firmware\ESP32_GENERIC.bin 0x0

# 仅 app 镜像烧到 0x10000：
uv run python scripts/flash.py firmware firmware\xxx-app.bin
```

具体烧录偏移以固件包说明为准。
