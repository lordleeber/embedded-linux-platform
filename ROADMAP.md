# Jetson Orin Nano + STM32 + Linux Driver + Yocto Learning Roadmap

## 目的

建立一條從 Linux userspace 一路深入到 Linux kernel、device driver、MCU firmware、Yocto、camera stack 與 Edge AI 的完整獨立實作路線。
最終希望具備：
- Linux kernel module 開發能力
- Character device driver
- Device Tree
- GPIO / IRQ
- I2C / SPI / UART driver
- Linux hwmon / sysfs / standard subsystem
- STM32 peripheral firmware
- Jetson ↔ STM32 通訊協定設計
- V4L2 / MIPI CSI camera driver 基礎
- Yocto / BitBake / OpenEmbedded 基礎
- `meta-tegra` 與 NVIDIA Jetson BSP 整合
- 自己建立 `meta-edge` layer 與可重現的 Jetson Linux image
---

## 文件結構

詳細實作已拆成每個 Phase 一個檔案。`ROADMAP.md` 只保留總覽、共通規則與索引。

| Phase | 主題 | Steps | 文件 |
|---:|---|---|---|
| 00 | 環境準備 | 1 | [phase00.md](phase00.md) |
| 01 | Linux Kernel Module 基礎 | 2, 3 | [phase01.md](phase01.md) |
| 02 | GPIO + LED + Interrupt | 4-a, 4-b, 5 | [phase02.md](phase02.md) |
| 03 | INA219 I2C Driver | 6, 7, 8 | [phase03.md](phase03.md) |
| 04 | OLED Driver | 9, 10-a, 10-b, 10-c | [phase04.md](phase04.md) |
| 05 | STM32F103 自製 Peripheral | 11, 12, 13 | [phase05.md](phase05.md) |
| 06 | Hardware Watchdog | 14, 15 | [phase06.md](phase06.md) |
| 07 | Jetson ↔ STM32 SPI | 16, 17-a, 17-b, 18-a, 18-b | [phase07.md](phase07.md) |
| 08 | poll / epoll / blocking I/O | 19, 20 | [phase08.md](phase08.md) |
| 09 | C++ Userspace Hardware Integration | 21, 22 | [phase09.md](phase09.md) |
| 10 | Jetson Orin Nano + Yocto + meta-tegra 實戰線 | 23 … 30 (10 steps) | [phase10.md](phase10.md) |
| 11 | IMX219 / V4L2 | 31, 32-a, 32-b, 33-a, 33-b | [phase11.md](phase11.md) |
| 12 | STM32N657 | 34-a, 34-b, 34-c, 35-a, 35-b, 35-c | [phase12.md](phase12.md) |

## 共通 Step 規則

每個 Step 必須是一個可以獨立 implement、build/run、verify、review 的單位。

```text
單一 Step 預估新增 code <= 800 lines
```

若合理預期超過 800 行，必須在實作前拆成 `Step N-a`、`Step N-b`、`Step N-c`…，不要先做完大型改動再事後切 commit。

每個 Step 應清楚描述：

1. 誰和誰互動。
2. controller/master 與 target/slave 分別是誰。
3. 資料如何流動。
4. 要新增哪些 driver / firmware / userspace component。
5. 使用哪些 Linux / MCU API 或 subsystem。
6. 實際驗收方法。
7. 這一步明確不做什麼。

## 建議執行方式

一次只執行一個 Step。完成、驗證、review 並修正後，再進入下一個 Step。
