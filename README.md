# embedded-linux-platform

在 Jetson Orin Nano 上，從 Linux userspace 一路做到 kernel driver、STM32 firmware、Yocto image 與 camera stack 的自學實作專案。每個 Step 同時交付可驗收的 code 和一章教材。

```text
STM32 firmware ──I2C/SPI──▶ Jetson kernel driver ──/dev, sysfs, hwmon, V4L2──▶ C++ platform-app
                                                                                 ▲
                                          Yocto meta-edge 把 modules、DT、app、systemd 打包成 image
```

上圖是整條路線的目標，目前做到 STM32 經 I2C 接上 Jetson driver；SPI、`platform-app`、Yocto 與 V4L2 還沒開始。

## 目前進度

已完成 Phase 00–05（Step 1–13），下一個是 Step 14。

| Phase | 主題 | Steps | 狀態 |
|---:|---|---|---|
| [00](phase00.md) | 環境準備 | 1 | 完成 |
| [01](phase01.md) | Linux Kernel Module 基礎 | 2, 3 | 完成 |
| [02](phase02.md) | GPIO + LED + Interrupt | 4-a, 4-b, 5-a, 5-b | 完成 |
| [03](phase03.md) | INA219 I2C Driver | 6-a, 6-b, 7, 8 | 完成 |
| [04](phase04.md) | OLED Driver | 9, 10-a, 10-b, 10-c | 完成 |
| [05](phase05.md) | STM32F103 自製 Peripheral | 11, 12-a, 12-b, 13 | 完成 |
| [06](phase06.md) | Hardware Watchdog | 14, 15 | 下一步 |
| [07](phase07.md) | Jetson ↔ STM32 SPI | 16, 17-a, 17-b, 18-a, 18-b | 未開始 |
| [08](phase08.md) | poll / epoll / blocking I/O | 19, 20 | 未開始 |
| [09](phase09.md) | C++ Userspace Hardware Integration | 21, 22 | 未開始 |
| [10](phase10.md) | Jetson Orin Nano + Yocto + meta-tegra | 23 … 30 | 未開始 |
| [11](phase11.md) | IMX219 / V4L2 | 31, 32-a, 32-b, 33-a, 33-b | 未開始 |
| [12](phase12.md) | STM32N657 | 34-a, 34-b, 34-c, 35-a, 35-b, 35-c | 未開始 |

完整規劃與 Step 規則見 [ROADMAP.md](ROADMAP.md)。

## 教材

用瀏覽器打開 [`docs/index.html`](docs/index.html) 就能從目錄開始讀（GitHub 上只會顯示 HTML 原始碼，要 clone 下來看）。每個 Step 一章，另有三章補充：開機早期韌體、UEFI 與 Device Tree 入門。

## 已實作的元件

| 路徑 | 內容 |
|---|---|
| `kernel/edge_test` | character device 與 ioctl |
| `kernel/edge_gpio` | LED 的 platform driver（`/dev/edge_gpio`） |
| `kernel/edge_button` | 按鍵 driver：GPIO IRQ、debounce、blocking read（`/dev/edge_button`） |
| `kernel/edge_ina219` | INA219 I2C client driver，接上 hwmon |
| `kernel/edge_oled` | SSD1306 OLED I2C client driver（`/dev/edge_oled`） |
| `kernel/edge_ctrl` | STM32 的 I2C client driver，register map 包成 sysfs 屬性 |
| `firmware/stm32f103/` | Blue Pill 的 I2C target firmware，見[它的 README](firmware/stm32f103/README.md) 與 [register map](firmware/stm32f103/docs/register-map.md) |
| `dts/` | 上面這些裝置共用的 Device Tree overlay |
| `apps/`、`tools/` | C++ 工具，例如 `edge_oled_ctl`、`telemetry_display`、`ina219_raw`、`oled_probe` |
| `include/` | kernel 和 userspace 共用的 header |
| `scripts/` | 環境檢查、overlay 安裝、實機驗收與教材檢查 |
| `tests/` | userspace 測試與協定向量 |
| `third_party/` | 廠商原始檔，原樣收錄不修改 |

## 環境與硬體

開發和執行都在 Jetson 上，目前的基準是 Jetson Orin Nano Engineering Reference Developer Kit Super、L4T R36.4.7、kernel 5.15.148-tegra（完整快照在 [docs/jetson-version.txt](docs/jetson-version.txt)）。kernel module 要對應實機的 kernel headers 版本。

各 Step 用到的硬體：

- LED、按鍵（Step 4–5）
- Waveshare UPS Power Module (C)，內含 INA219（Step 6–8、10-c）
- SSD1306 128x64 I2C OLED（Step 9–10）
- STM32F103 Blue Pill 與 ST-Link V2（Step 11 起）

接線與 pin mapping 見 [docs/hardware-wiring.md](docs/hardware-wiring.md)。

## 建置與測試

沒接硬體也能跑這幾項。需要硬體的測試在裝置不存在時會 skip，所以這裡通過不代表實機驗收通過。

```bash
# 環境檢查
bash scripts/check_host_env.sh

# C++ 工具與協定向量（產物在 build/）
cmake -S . -B build && cmake --build build

# 全部 userspace 測試
python3 -m unittest discover -s tests -v

# 教材檢查
python3 scripts/check_book.py docs
```

kernel module 和 overlay 要另外建置。overlay 安裝後要重開機才生效：

```bash
make -C kernel/edge_test
make -C dts
sudo python3 scripts/install_edge_gpio_overlay.py install dts/edge-gpio-overlay.dtbo
```

STM32 firmware 用 PlatformIO 建置：

```bash
~/.platformio/penv/bin/pio run -d firmware/stm32f103
```

實機驗收腳本是 `scripts/verify_*.sh`，多半需要 root，有些要有人在板子旁看現象或操作硬體。每個 Step 的完整指令、接線前提和注意事項都在 [CLAUDE.md](CLAUDE.md) 的「指令」段落。

## 開發方式

- 一個 Step 是一個 branch、一個 PR，新增 code 上限約 800 行，超過就先拆成 `Step N-a`、`N-b`。
- 先寫測試再實作。需要實體硬體的部分，也先把驗收步驟寫成腳本。
- 每個 PR 同時交付 code 和一章教材 `docs/stepNN.html`。
- 驗收數字和踩過的坑記在 [docs/baseline.md](docs/baseline.md)。
