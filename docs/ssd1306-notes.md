# SSD1306 筆記（Step 9）

對象：128x64、I2C 介面的 OLED 模組（SSD1306 控制器；模組板上的元件沒有逐一核對）。
出處：SSD1306 datasheet Rev 1.1（Solomon Systech）的 8.1.5 I2C、9 Command Table、10 Command Descriptions、
以及 charge pump 的 application note。程式裡的 byte 全部在 `tools/ssd1306.h`，向量在 `tests/test_ssd1306.cpp`。

## 誰和誰互動

```text
oled_probe (userspace) ── ioctl(I2C_RDWR) ──▶ i2c-dev ──▶ Tegra I2C controller (master)
                                                              │ SDA/SCL (header pin 27/28, c240000.i2c)
                                                              ▼
                                                        SSD1306 (target, 0x3C)
```

Jetson 是 controller（master），OLED 是 target（slave）。資料只往一個方向走：**SSD1306 在 I2C 模式下不能讀回 display RAM**，
所以程式無法自己確認畫面，只能確認每個 byte 都有 ACK；畫面要靠人眼（`scripts/verify_oled_probe.sh` 會逐項問）。

## 一個 I2C write 的格式

```text
START | 0x3C<<1 | W | control byte | stream ... | STOP
```

control byte 的 bit 7 是 Co、bit 6 是 D/C#，其餘為 0：

| control byte | 意思 |
|---|---|
| `0x00` | Co=0、D/C#=0：後面全是 **command** |
| `0x40` | Co=0、D/C#=1：後面全是 **GDDRAM data**（像素） |
| `0x80` / `0xC0` | Co=1：只有下一個 byte 是 command / data，之後還要再一個 control byte（本專案不用） |

把 ASCII `"EDGE"` 直接寫過去不會出現文字：`0x45 0x44 ...` 會被當成 command 或像素。文字要先在 framebuffer 裡畫成點，再用 `0x40` 送。

## 初始化順序（`ssd1306::init_sequence()`）

每次執行都整串送，不假設前一次留下的狀態（驗收的 power-cycle 與 i2ctransfer 打亂測試就是在驗這件事）：

| bytes | 指令 | 為什麼要寫 |
|---|---|---|
| `AE` | display off | 設定期間不顯示 |
| `D5 80` | clock divide / oscillator | reset 值，寫明比較保險 |
| `A8 3F` | multiplex ratio = 64 | 128x64 面板；128x32 是 `1F` |
| `D3 00` | display offset 0 | |
| `40` | start line 0 | |
| `8D 14` | **charge pump on** | 模組只給 3.3 V，面板要的高壓由內部 charge pump 產生；沒開會「指令都 ACK 但螢幕全黑」 |
| `20 00` | horizontal addressing | 寫完一個 page 的 128 個 column 自動換下一個 page |
| `A1` | segment remap | column 127 → SEG0；不寫的話左右鏡像 |
| `C8` | COM scan 反向 | page 0 在上；不寫的話上下顛倒 |
| `DA 12` | COM pins 配置 | 128x64 用 alternative；128x32 是 `02` |
| `81 CF` | contrast | |
| `D9 F1` | pre-charge | internal charge pump 用的值 |
| `DB 40` | VCOMH | |
| `2E` | scroll off | 有在 scroll 時寫 RAM 會亂 |
| `A4` | 顯示跟著 RAM | `A5` 是全亮 |
| `A6` | 正常（非反白） | `A7` 是反白 |

`AF`（display on）不在 init 裡，**寫完第一張 frame 後才送**，避免先閃一下 RAM 裡的舊內容（上電後 RAM 是隨機的）。

## GDDRAM 版面

128 × 64 個點分成 8 個 page，每個 page 8 列高。一個 byte 是**直的** 8 個點：

```text
frame[page * 128 + x] 的 bit n  =  點 (x, 8 * page + n)，bit 0 在上
```

例：(0,0) → `frame[0]` bit 0；(3,9) → `frame[131]` bit 1；(127,63) → `frame[1023]` bit 7。
5x7 字型表也是一欄一個 byte、bit 0 在上，和 GDDRAM 方向一致，所以 scale 1 時字型的 byte 可以原樣放進 page 0。

## 傳一張 frame（`ssd1306::frame_writes()`）

```text
0x00 21 00 7F 22 00 07     column 0..127、page 0..7（同時把位址指標拉回 (0,0)）
0x40 <128 bytes page 0>
...
0x40 <128 bytes page 7>
```

先送 window 指令，前一次留下的位址指標就不影響這次。一個 page 一個 message（129 bytes）；I2C_RDWR 沒有 SMBus 的 32 bytes 上限。

## 失敗長什麼樣子

| 現象 | 原因 |
|---|---|
| `oled_probe` 結束碼 1、`Remote I/O error` | 位址沒 ACK：沒接、沒電、位址錯（有些模組是 0x3D，背面焊點可改） |
| 全部 ACK、螢幕全黑 | 沒開 charge pump（`8D 14`），或沒送 `AF` |
| 字左右相反 / 上下顛倒 | `A1` / `C8` 沒寫或寫反 |
| 隔一行才有點、字被拉長 | `DA` 的 COM pins 配置錯（128x32 與 128x64 不同）或 `A8` 不對 |
| 畫面錯位、從中間開始 | 沒先送 window 指令，位址指標停在前一次的位置 |

## 斷電與「偷供電」（Step 9 實測，2026-10-13）

只拔 VCC、SDA / SCL / GND 還接著時：螢幕**變暗但 EDGE 還看得到**，`oled_probe` 照樣全部 ACK（結束碼 0）。
最可能的路徑是 bus 的 pull-up 經 SSD1306 腳位的 ESD 保護二極體餵進晶片的 VDD（推論，沒有量電壓）。
所以「拔 VCC」不等於 power-cycle。驗收改成四條線全拔、再接上（先接 GND），並在送任何指令前確認螢幕全黑：
上電 reset 後 display 是 OFF（`AE`），全黑才證明晶片真的斷過電。

## 單一指令的實際效果（Step 9 實測，2026-10-13）

在畫著 EDGE 的面板上一次只送一個指令（`i2ctransfer -y 1 w<n>@0x3c 0x00 <cmd...>`），人眼回報：

| 指令 | 看到的 |
|---|---|
| `A7` | 白底黑字（反白） |
| `C0` | 上下顛倒 |
| `A0` | 左右鏡像，**立刻生效**（不是只影響之後寫入的資料） |
| `20 01` | 不變（addressing mode 只影響之後怎麼寫） |
| `81 00` | 全黑（contrast 0 在這片模組上不只是變暗） |

另一個教訓：螢幕關著（`AE`）時送這些指令，人什麼都看不到；要先確認 display 是開的、有已知畫面。
