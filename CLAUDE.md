# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 專案現況

這是一個 Jetson Orin Nano + STM32 + Linux driver + Yocto 的自學實作專案。目前 repo **只有規劃文件**，還沒有任何程式碼、build system 或測試框架：

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

## 搭配的 skills：每個 Step 同時交付 code 與一章教材

本專案每個 Step 都照下面兩個 skill 進行，同一個 PR 裡同時交付 code 和教學章：

1. **`/step-execution`** 負責主流程：讀基準 → 開分支 → 先寫測試 → 實作 → 對照基線驗證 → 同步文件 → 冷讀章節 → 開 PR。
2. **`/incremental-html-textbook`** 負責寫教學章。要等 code 驗證通過後才動筆，而且要由寫 code 的同一個 session 來寫。
3. 章節寫完、開 PR 前，把**該章那一頁**交給 `cold-read` 掃一遍。回報內容要逐條回頭核對過才動手。
4. PR 開出後，使用者會在另一個乾淨的 session 跑 `/code-review`。不要在同一個 session 自己再審一輪 code。

這兩個 skill 會參照 repo 慣例，本 repo 的慣例如下：

| 項目 | 本 repo 的規定 |
|---|---|
| 教學章 | `docs/stepNN.html`，編號補零成兩位數（`step01.html`、`step23.html`），拆分的 Step 加上字尾（`step10a.html`）。單檔自足、深色主題，新章複製「最近一章」再修改 |
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

目前只有 `check_book.py` 已經放進 repo，其餘都還沒建立：

- Host/target 環境檢查：`scripts/check_host_env.sh`（Step 1）
- 教材全書驗收：`python3 scripts/check_book.py docs`（結束碼：0 = 通過、1 = 檢查沒過、2 = 環境或參數有問題）
- Kernel module：在 `kernel/<name>/` 下 `make`，以 `insmod` / `rmmod` 載入卸載，觀察 `dmesg`
- C++ userspace：CMake
- Yocto：kas + BitBake（Phase 10）
