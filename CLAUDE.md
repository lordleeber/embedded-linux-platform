# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 專案現況

這是一個 Jetson Orin Nano + STM32 + Linux driver + Yocto 的自學實作專案。Step 1 已新增環境檢查腳本與版本快照；Step 2 新增 `kernel/edge_test` character device 與驗收腳本 `scripts/verify_edge_test.sh`；Step 3 新增 ioctl 控制通道、共用 header `include/edge_test_ioctl.h` 與 C++ CLI（`apps/`，CMake 建置）；Step 4-a 新增 userspace GPIO 程式 `apps/edge_gpio_blink.cpp` 與 pad 設定腳本 `scripts/pad_pin29.py`（Step 4 拆成 4-a userspace / 4-b kernel driver）；Step 4-b 新增 platform driver `kernel/edge_gpio`（`/dev/edge_gpio`）與 DT overlay `dts/edge-gpio-overlay.dts`（含 pad 的 pinctrl 狀態）；Step 5 拆成 5-a userspace / 5-b kernel driver：5-a 新增 `apps/edge_gpio_button.cpp`（gpiolib-cdev 的 edge event，不寫 driver），5-b 新增按鍵 driver `kernel/edge_button`（`/dev/edge_button`，GPIO IRQ + debounce + blocking read）、事件格式 `include/edge_button.h` 與 C++ `apps/edge_button_wait.cpp`，按鍵節點加在同一份 overlay；Step 6 拆成 6-a 讀懂廠商範例 / 6-b 自己的 userspace 工具：6-a 把 Waveshare UPS Power Module (C) 的 `ina219.py` 原樣收進 `third_party/waveshare_ups_c/`（不修改，SHA-256 釘住），配測試與驗收腳本 `scripts/verify_ina219_sample.sh`；6-b 新增不用 Python library 的 `tools/ina219_raw.cpp`（i2c-dev `I2C_RDWR`，整數換算在 `tools/ina219_decode.h`）、驗收腳本 `scripts/verify_ina219_raw.sh` 與 register 筆記 `docs/ina219-registers.md`。每個 Step 都有一章教材 `docs/stepNN.html`：

- `ROADMAP.md` — 總覽、Phase 索引、共通 Step 規則（先讀這份）
- `phase00.md` … `phase12.md` — 每個 Phase 的目的與 Step 詳細規劃

Build / test 指令會隨各 Step 落地而出現；新增時請回來更新本檔的「指令」段落，不要憑空假設。

## 工作單位：Step

- 一個 Step = 一個 branch = 一個 PR。一次只做一個 Step，完成、驗證、review 後才進下一個。
- Branch 名稱用 `step-N`（拆分的用 `step-10a`），PR 標題用 `step-N: <一句話目標>`。
- 動工前先讀對應 `phaseNN.md` 裡該 Step 的區塊（包在 `<!-- STEP_PLAN_START -->` / `<!-- STEP_DETAIL_START -->` 標記內），特別是「預期檔案」「驗證 / 驗收條件」「這一步不做」。**「這一步不做」是硬性範圍邊界**，不要提前實作後面 Step 的功能。
- Step 編號跨 Phase 連續（Phase 10 是 Step 23–30，而 Phase 11 從 Step 31 開始）。

### 必須遵守

1. **TDD：先寫測試再實作。** 每個 Step 先寫出會失敗的測試（regression test、negative test、protocol test vectors、fake/mock 注入等，依 Step 的驗證條件而定），再寫實作讓它通過。需要實體硬體才能驗的部分，也要先把驗收步驟寫成可執行的 script 或 checklist。
2. **Step 大小上限約 800 行新增 code。** 若預估遠超過（例如 ~1200 行），必須在**實作前**拆成 `Step N-a`、`Step N-b`、`Step N-c`…（ROADMAP 已有 `10-a`、`17-a`、`29-a` 等前例），並同步更新 `ROADMAP.md` 的索引表與對應 `phaseNN.md`。不要先做完大改動再事後切 commit。
3. 每個 Step 的描述要交代：誰和誰互動、controller/master 與 target/slave、資料流、新增哪些元件、用到哪些 Linux/MCU API、驗收方法、明確不做什麼。

## 搭配的 skill：每個 Step 同時交付 code 與一章教材

本專案每個 Step 都照 **`/step-execution`** 進行，同一個 PR 裡同時交付 code 和教學章：

1. 主流程：讀基準 → 開分支 → 先寫測試 → 實作 → 對照基線驗證 → 同步文件 → 寫教學頁 → 開 PR。
2. 寫教學頁時載入 **`/incremental-html-textbook`**，照它用 artifact 的做法寫，但**不發佈到 claude.ai**，寫成完整的單檔 HTML 存成 `docs/stepNN.html`。要等 code 驗證通過後才動筆，而且要由寫 code 的同一個 session 來寫。
3. **不跑 `cold-read`**。Step 1、2 的章是用舊做法（共用 `style.css` + 冷讀）寫的，保留原樣。
4. PR 開出後，使用者會在另一個乾淨的 session 跑 `/code-review`。不要在同一個 session 自己再審一輪 code。

本 repo 的慣例如下：

| 項目 | 本 repo 的規定 |
|---|---|
| 教學章 | `docs/stepNN.html`，編號補零成兩位數（`step01.html`、`step23.html`），拆分的 Step 加上字尾（`step10a.html`）。artifact 風格的完整單檔 HTML：CSS/JS inline、只做暗色主題，以桌面瀏覽器閱讀為準（不要求手機寬度），頁面寬度統一 1080px（最外層 `max-width: 67.5rem`，和 Step 1、2 的章一致），外部資源只用 Google Fonts。頂部和底部各放一組導覽（↑ 目錄、← 前章、後章 →），`check_book.py` 靠它驗章節鏈 |
| 教材目錄 | `docs/index.html`，卡片順序要和章節順序一致 |
| 新章上線 | 在前一章頂部和底部的 pagenav 都補上 next 連結，並在 `index.html` 加卡片，再跑 `python3 scripts/check_book.py docs`（這份是從 skill 複製進 repo 的；skill 版本更新時要同步過來） |
| 基線與踩坑紀錄 | `docs/baseline.md`：每個 Step 追加驗收數字、對照方法與容差，以及踩到的坑（坑要寫出「原本以為」什麼）。下一個 Step 開工前要先讀它 |
| 驗收證據 | 貼在 PR 描述。需要實體硬體才能驗的項目（`dmesg`、示波現象、按鍵、LED 等）要照實標示哪些已實測、哪些尚未實測 |
| 範圍外缺陷 | 不要順手修，記下來排進 ROADMAP 後續的 Step |
| 快照同步 | 改到教材有引用的函式或檔案時，用 `grep -l '<名稱>' docs/*.html` 找出受影響的章並一起更新。如果 PR 動到這類檔案卻沒改 docs，視為一個 review finding |

## 規劃中的架構（跨 Phase 的大方向）

各 Phase 規劃的目錄慣例（實際建立時以該 Step 的「預期檔案」為準）：

| 路徑 | 內容 |
|---|---|
| `scripts/` | host/target 環境檢查等腳本（Step 1 的 `check_host_env.sh`） |
| `docs/` | bring-up、接線/pin mapping、各元件筆記 |
| `kernel/<name>/` | 各 out-of-tree kernel module（`edge_test`、`edge_gpio`、`edge_ina219` …），各自有 `Makefile` |
| `third_party/` | 廠商原始檔（原樣收錄、不修改；如 `waveshare_ups_c/ina219.py`） |
| `include/` | kernel/userspace 共用 header（如 ioctl 定義）與 `include/platform/` C++ 介面 |
| `dts/` | Device Tree overlay |
| `apps/`、`src/platform/`、`tools/` | C++ userspace（CLI、`platform-app`、probe 工具） |
| `tests/` | userspace regression tests |
| `firmware/stm32f103/`、STM32N657 | MCU firmware（含 register map 文件） |
| `meta-edge/` | 自建 Yocto layer（疊在 `meta-tegra` / OE4T 上，用 kas 建置） |

整體資料流的主軸：

```text
STM32 firmware ──I2C/SPI──▶ Jetson kernel driver ──/dev, sysfs, hwmon, V4L2──▶ C++ platform-app
                                                                                 ▲
                                          Yocto meta-edge 把 modules、DT、app、systemd 打包成 image
```

設計要點（跨多個 Phase 反覆出現）：

- Kernel driver 走標準 subsystem：character device → platform driver + Device Tree → I2C/SPI client → hwmon/sysfs → V4L2 subdev。使用 descriptor-based GPIO API（`devm_gpiod_get()`），不用舊的 global GPIO number API。
- ioctl 結構只用固定大小型別（32/64-bit 相容），ioctl number 不可撞號。
- Jetson ↔ STM32 協定（I2C register map、SPI framing）要能從 malformed packet 重新同步，並有 test vectors。
- C++ userspace 透過 `include/platform/` 的抽象介面存取硬體，application policy 不直接碰 `/dev` / sysfs；測試用 fake/mock 注入電壓、I/O error、timeout 等情境，不需實體拔線。
- Jetson 是 target；Yocto image 在 x86-64 Ubuntu host 上建置後再 flash。kernel module 必須對應 Jetson 實際的 L4T/kernel headers 版本（記錄在 `docs/jetson-version.txt`）。

## 指令

目前已實作 Step 1–3、4-a、4-b、5-a、5-b、6-a、6-b 的指令，其餘功能尚未建立：

- Jetson target 環境檢查：`bash scripts/check_host_env.sh`（Step 1）；更新快照用 `bash scripts/check_host_env.sh --record docs/jetson-version.txt`
- 全部 userspace 測試：`python3 -m unittest discover -s tests -v`
- 教材全書驗收：`python3 scripts/check_book.py docs`（結束碼：0 = 通過、1 = 檢查沒過、2 = 環境或參數有問題）；章裡「N 個測試」的宣稱寫成 `<span data-tests="tests/<file>.py">N</span>`，用 `python3 scripts/check_test_counts.py docs` 核對（同一套結束碼）
- 教材共用樣式：改 `docs/style.css` / `docs/enhance.js`（來自 skill 的 assets）後跑 `python3 ~/.claude/skills/completed-repo-to-html-textbook/scripts/inline_assets.py docs` 重新內嵌
- Kernel module：在 `kernel/<name>/` 下 `make`，以 `insmod` / `rmmod` 載入卸載，觀察 `dmesg`
- Step 2 `edge_test` 驗收（需 root，sudo 要密碼，請使用者執行）：`sudo bash scripts/verify_edge_test.sh 3`；device 測試單獨跑：`python3 -m unittest discover -s tests -p test_edge_test_device.py -v`（module 未載入時 skip）
- C++ userspace：在 repo 根目錄 `cmake -S . -B build && cmake --build build`（產出 `build/edge_test_cli`、`build/test_edge_device`；`build/` 不入庫）。`test_edge_device` 結束碼 0/1/77（77 = 裝置不存在而 skip）
- Step 3 ioctl 驗收併在同一支 `sudo bash scripts/verify_edge_test.sh 3` 裡（每輪多跑 C++ ioctl 測試、CLI 測試、reload 後 value 歸零）
- Step 4-a userspace GPIO（LED 接 header pin 29 → 330 Ω → LED → pin 30）：`build/edge_gpio_blink`（CMake 產出，無參數，固定 gpiochip0 line 105 閃 5 次）。JP6 開機 pad 是 tristate，要先 `sudo python3 scripts/pad_pin29.py open`（`show` / `close`；重開機即失效）。驗收（需 root，請使用者執行並看 LED）：`sudo bash scripts/verify_edge_gpio_blink.sh`；實機測試單獨跑：`EDGE_GPIO_HW=1 python3 -m unittest discover -s tests -p test_edge_gpio_blink.py -v`
- Step 4-b kernel GPIO driver：`make -C dts`（cpp + dtc 編 overlay，產出 active-high / active-low 兩個 dtbo；`*.dtbo` 不入庫）；安裝到 extlinux.conf 的 DEFAULT label：`sudo python3 scripts/install_edge_gpio_overlay.py install dts/edge-gpio-overlay.dtbo`（`remove` 移除；兩者都要重開機才生效，這台沒有 runtime overlay）。module 在 `kernel/edge_gpio/` 下 `make`。驗收（需 root，請使用者執行並看 LED）：`sudo bash scripts/verify_edge_gpio.sh [--blink] [cycles]`，會依 `/proc/device-tree/edge-led` 是否存在自動切換「不 probe」或「完整驗收」模式。device 測試：`python3 -m unittest discover -s tests -p test_edge_gpio_device.py -v`（module 未載入時 skip；`EDGE_GPIO_REQUIRE=1` 時改為 fail）
- Step 5-a userspace 按鍵（接線同 5-b）：`build/edge_gpio_button [count]`（CMake 產出，固定 gpiochip0 line 43，edge event + 20 ms debounce，輸出格式同 `edge_button_wait`，結束碼 0/1/2；`edge_button.ko` 載入時 line 被佔用）。請求 line 後約 20 ms 內 pin 讀到 0，程式會先等 50 ms 再開始，`gpioget` 單次讀值因此不可靠。驗收（需 root，要有人按按鍵，請使用者執行）：`sudo bash scripts/verify_edge_gpio_button.sh [--no-press]`；實機測試（不按按鍵，gpio 群組即可）：`EDGE_GPIO_HW=1 python3 -m unittest discover -s tests -p test_edge_gpio_button.py -v`
- Step 5-b kernel GPIO 按鍵 IRQ（按鍵接 header pin 33 → 按鍵 → pin 34 GND，pin 33 另經 330 Ω 上拉到 pin 1（3.3 V）；header GPIO 經 TXB0108，SoC 內部上拉無效）：overlay 同 4-b（改完要重新 `make -C dts`、install、重開機）。module 在 `kernel/edge_button/` 下 `make`；`build/edge_button_wait [count]`（CMake 產出，blocking read 印 N 筆事件，結束碼 0/1/2）。驗收（需 root，要有人按按鍵，請使用者執行）：`sudo bash scripts/verify_edge_button.sh [--no-press]`，依 `/proc/device-tree/edge-button` 是否存在切換「不 probe」或「完整驗收」。device 測試（不按按鍵）：`python3 -m unittest discover -s tests -p test_edge_button_device.py -v`（module 未載入時 skip；`EDGE_BUTTON_REQUIRE=1` 時改為 fail）
- Step 6-a INA219（UPS Power Module (C) 依官方說明接上並供電給 Jetson；INA219 在 `i2c-7` = header pin 3/5，位址 0x41；使用者在 `i2c` 群組即可，不需 root）：廠商範例 `python3 -u third_party/waveshare_ups_c/ina219.py`（每 2 秒一輪，Ctrl-C 結束；**啟動時會寫入 Calibration 與 Config**）。掃描要用 `i2cdetect -y -r 7`（Tegra 不支援 Quick Write，不加 `-r` 時 0x41 被跳過）。驗收：`bash scripts/verify_ina219_sample.sh [--no-unplug]`（不加參數時要有人拔插 UPS 的 DC adapter）；實機測試：`EDGE_INA219_HW=1 python3 -m unittest discover -s tests -p test_ina219_sample.py -v`
- Step 6-b INA219 raw（接線同 6-a，不需 root）：`build/ina219_raw [--bus N] [--addr 0xNN]`（CMake 產出，預設 bus 7 / 0x41，**只讀不寫**，印六個 register 與換算；結束碼 0/1/2，位址沒 ACK 時 1 + `Remote I/O error`）。`i2cget -y 7 0x41 <reg> w` 印出的值 byte 是反的（SMBus word 低位先送）。decode 測試向量：`build/test_ina219_decode`。驗收：`bash scripts/verify_ina219_raw.sh [--no-unplug]`（會用 `i2cset` 把 Calibration 原值寫回）；實機測試：`EDGE_INA219_HW=1 python3 -m unittest discover -s tests -p test_ina219_raw.py -v`
- 教材程式碼節錄比對：`python3 scripts/check_listings.py docs`（0/1/2）。改到教材有引用的原始檔後一定要跑
- Yocto：kas + BitBake（Phase 10）
