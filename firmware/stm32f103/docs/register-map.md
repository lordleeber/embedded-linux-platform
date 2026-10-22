# STM32F103 I2C target — register map v1.0（Step 12-a）

Controller（master）是 Jetson，target（slave）是 Blue Pill 的 I2C1（PB6 = SCL、PB7 = SDA），
7-bit 位址 **0x42**。每個 register 都是 1 byte。程式用的拷貝是 `Core/Inc/i2c_target.h`，測試讓兩份一致。

## 分區

| 範圍 | 用途 |
|---|---|
| 0x00–0x0F | identification / version |
| 0x10–0x1F | sensor / input（Step 12-b：ADC、按鍵） |
| 0x20–0x2F | output control |
| 0x30–0x3F | health / watchdog |

其餘位址沒有定義。

## Register

| 位址 | 名稱 | 存取 | 值 / reset 預設 | 說明 |
|---|---|---|---|---|
| 0x00 | DEVICE_ID | RO | 0xED | 固定值，用來確認接上的是這份 firmware |
| 0x01 | FW_MAJOR | RO | 0x00 | firmware 版本 major |
| 0x02 | FW_MINOR | RO | 0x02 | firmware 版本 minor（Step 11 = 0.1，Step 12-a = 0.2） |
| 0x03 | PROTOCOL_VERSION | RO | 0x10 | register map 版本：高 4 bit major、低 4 bit minor（1.0） |
| 0x20 | LED_CONTROL | RW | 0x00 | 0 = 板載 LED（PC13）滅，1 = 亮 |
| 0x30 | STATUS | RW1C | 0x80 | 錯誤旗標，見下表；寫 1 的 bit 清掉 |
| 0x31 | WATCHDOG_STATUS | RO | 0x00 | 預留給 watchdog（Phase 6）；現在固定 0 = 沒有 watchdog |

沒有定義的位址讀到 0xFF。

## STATUS（0x30）

| bit | 名稱 | 什麼時候設起來 |
|---|---|---|
| 0 | RO_WRITE | 寫了 RO register（0x00–0x03、0x31），資料被丟掉 |
| 1 | UNMAPPED_WRITE | 寫了沒定義的位址，資料被丟掉 |
| 2 | BAD_VALUE | 寫入的值 register 不接受（LED_CONTROL 寫 0、1 以外），資料被丟掉 |
| 3 | BUS_ERROR | I2C1 偵測到 BERR / ARLO / OVR；firmware 隨後重設了 I2C1 周邊 |
| 7 | RESET | 開機或 reset 後設起來：Jetson 看到它就知道板子重開過 |

bit 4–6 保留，讀到 0，寫入時忽略。

- **write-1-to-clear**：寫 `0x01` 只清 bit 0，寫 `0xFF` 全清，寫 `0x00` 什麼都不清。清 STATUS 本身不算錯誤。
- 讀 STATUS 不會清任何 bit。不用 read-to-clear 的原因：F103 在對方 NACK 之前會先把下一個 byte 放進 DR（TXE），
  那個 byte firmware「讀」過、卻沒送到 Jetson。讀 0x2F 時 firmware 會順便取一次 0x30；
  如果讀取會清旗標，錯誤就在沒人看到的情況下消失。
- 旗標會累積，直到 Jetson 清掉。同一個 bit 在兩次讀取之間發生兩次，看起來和一次一樣。
- 讀取任何位址（包括沒定義的）都不算錯誤：多 byte 讀取本來就可能讀過 register 的尾端。
- 誰寫 `0xFF` 都會連 RESET 一起清掉，`scripts/verify_stm32_i2c.sh` 也是（開頭與結束各一次）。要用 RESET 判斷「板子重開過」的程式，不要和驗收腳本同時用。

## Transaction

```text
寫：START 0x42+W  reg  data0 data1 ...  STOP              data0 → reg、data1 → reg+1、...
讀：START 0x42+W  reg  RESTART  0x42+R  b0 b1 ...  STOP   b0 = reg、b1 = reg+1、...
```

- 寫入的第 1 個 byte 是 register pointer，之後每個資料 byte 寫到下一個位址（**auto-increment**）。
  每個資料 byte 各自檢查：`i2ctransfer w3@0x42 0x20 0x01 0x00` 會把 LED 打開，再因為 0x21 沒定義設 UNMAPPED_WRITE。
- 讀取同樣 auto-increment；過了 0xFF 回到 0x00。
- **auto-increment 只在同一筆 transaction 裡有效。** pointer 只由寫入設定（就是寫入的第 1 個 byte），
  讀取不會移動它；沒先寫 pointer 的讀取（`i2ctransfer r2@0x42`）從上次寫入的 pointer 開始。
  只寫 pointer、沒有資料的寫入是合法的。
- 多 byte 的值（Step 12-b 起，例如 ADC）**little-endian**：低位元組在較小的位址，一次讀完就是 LOW、HIGH 的順序。
  兩個 byte 是否來自同一次取樣，由該 register 的說明定義。

## 不合法的存取

| 情況 | bus 上 | 結果 |
|---|---|---|
| 寫 RO register | ACK | 丟掉，值不變，STATUS bit 0 |
| 寫沒定義的位址 | ACK | 丟掉，STATUS bit 1 |
| LED_CONTROL 寫 0、1 以外的值 | ACK | 丟掉，LED 保持原狀，STATUS bit 2 |
| 讀沒定義的位址 | ACK | 回 0xFF，不算錯誤 |
| bus error（BERR / ARLO / OVR） | — | transaction 在這裡結束：出錯前收到的 byte（包括 pointer 與已寫入的資料）已經生效，之後的 byte 不算；STATUS bit 3，I2C1 重設 |

F103 的 I2C 在 firmware 看到 byte 之前就已經由硬體回 ACK，所以 target 沒辦法用 NACK 拒絕一個值；
錯誤改由 STATUS 回報。

bus error 沒有 rollback：Jetson 看到 BUS_ERROR，就把那一筆寫入整筆重送。目前所有可寫的 register
（LED_CONTROL、STATUS 的 write-1-to-clear）重送都沒有副作用，所以這樣做就夠了；之後加的可寫 register 也要維持這一點。

## 版本規則

- **PROTOCOL_VERSION**（0x03）描述這份 register map：高 4 bit 是 major、低 4 bit 是 minor。
  - minor 加 1：新增 register（用沒定義的位址，之前讀到 0xFF）或新增 STATUS bit（用保留的 bit，之前讀到 0）。舊的 register 意思不變。
  - major 加 1、minor 歸 0：既有 register 的意思、寬度、存取方式改了，或 transaction 規則改了。
  - Jetson 端認得 M.n 時，可以用 major = M 且 minor ≥ n 的裝置；major 不同就不要碰。
  - Step 11 的 firmware 沒有 0x03，讀到 0xFF（major 15），視為「版本規則之前」的 firmware。
  - Step 12-a 是 1.0（auto-increment 改了 transaction 規則，所以從 Step 11 算是 major 改變）；Step 12-b 加 ADC 與按鍵預計是 1.1。
- **FW_MAJOR / FW_MINOR**（0x01 / 0x02）描述 firmware 本身：每次發佈都要改，protocol 沒變也一樣（例如只修 bug）。
