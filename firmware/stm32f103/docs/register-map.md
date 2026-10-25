# STM32F103 I2C target — register map v1.1（Step 12-a、12-b）

Controller（master）是 Jetson，target（slave）是 Blue Pill 的 I2C1（PB6 = SCL、PB7 = SDA），
7-bit 位址 **0x42**。每個 register 都是 1 byte。程式用的拷貝是 `Core/Inc/i2c_target.h`，測試讓兩份一致。

## 分區

| 範圍 | 用途 |
|---|---|
| 0x00–0x0F | identification / version |
| 0x10–0x1F | sensor / input：ADC、按鍵 |
| 0x20–0x2F | output control |
| 0x30–0x3F | health / watchdog |

其餘位址沒有定義。

## Register

| 位址 | 名稱 | 存取 | 值 / reset 預設 | 說明 |
|---|---|---|---|---|
| 0x00 | DEVICE_ID | RO | 0xED | 固定值，用來確認接上的是這份 firmware |
| 0x01 | FW_MAJOR | RO | 0x00 | firmware 版本 major |
| 0x02 | FW_MINOR | RO | 0x03 | firmware 版本 minor（Step 11 = 0.1，12-a = 0.2，12-b = 0.3） |
| 0x03 | PROTOCOL_VERSION | RO | 0x11 | register map 版本：高 4 bit major、低 4 bit minor（1.1） |
| 0x10 | ADC_LOW | RO | 0x00 | PA0 的 12-bit ADC 值，bit 7:0 |
| 0x11 | ADC_HIGH | RO | 0x00 | ADC 值的 bit 11:8，放在 bit 3:0；bit 7:4 讀 0 |
| 0x12 | BUTTON_STATE | RO | 0x00 | bit 0 PRESSED：PA1 的按鍵按著（消除彈跳後）；bit 7:1 讀 0 |
| 0x13 | BUTTON_PRESSES | RO | 0x00 | 開機以來消除彈跳後的按下次數，8-bit，255 之後回到 0 |
| 0x20 | LED_CONTROL | RW | 0x00 | 0 = 板載 LED（PC13）滅，1 = 亮 |
| 0x30 | STATUS | RW1C | 0x80 | 錯誤旗標，見下表；寫 1 的 bit 清掉 |
| 0x31 | WATCHDOG_STATUS | RO | 0x00 | 預留給 watchdog（Phase 6）；現在固定 0 = 沒有 watchdog |

沒有定義的位址讀到 0xFF。

## 輸入（0x10–0x13，Step 12-b）

- **ADC**：ADC1 channel 0 = **PA0**（Blue Pill 的 A0），**12-bit**、right-aligned，0–4095 對應 0 V 到 **VDDA**
  （Blue Pill 上是 3.3 V，和 MCU 同一個電源；沒有外部參考電壓）。firmware 開機時做一次校正，之後連續轉換：
  取樣時間 239.5 cycles，ADC clock 12 MHz，約每 21 µs 一個值。值不做平均。
- **讀 ADC 要一次讀 2 個 byte**：`i2ctransfer w1@0x42 0x10 r2@0x42` → LOW、HIGH（**little-endian**），值 = HIGH × 256 + LOW。
- **快照**：每一筆讀取開始時（Jetson 送出 0x42 + R 的那一刻），firmware 把 ADC、BUTTON_STATE、BUTTON_PRESSES
  一次複製成快照，這筆讀取的所有 byte 都來自它。所以同一筆讀取的 LOW 和 HIGH 一定是同一次轉換；
  分成兩筆讀（先讀 0x10、再讀 0x11）可能來自不同次轉換，不要這樣讀。
  快照在「讀取開始」時拍，和讀了哪幾個 byte 無關：F103 在 NACK 前多取的那個 byte 不會觸發任何事。
- **按鍵**：**PA1**（A1）開內部上拉，按鍵另一端接 GND，按下 = 低電位。SysTick 每 1 ms 取樣一次，
  電位要連續維持 **20 ms** 才算改變狀態（消除彈跳）。開機時就按著，20 ms 後算一次按下。
- **BUTTON_PRESSES** 讓 Jetson 不漏掉兩次輪詢之間的短按：記下上次讀到的值，相減（mod 256）就是這段時間按了幾次。
  它是唯讀的，不能清除；讀取也沒有副作用。
- 0x10–0x13 都是 RO，寫入會設 STATUS 的 RO_WRITE。

## STATUS（0x30）

| bit | 名稱 | 什麼時候設起來 |
|---|---|---|
| 0 | RO_WRITE | 寫了 RO register（0x00–0x03、0x10–0x13、0x31），資料被丟掉 |
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
- 多 byte 的值（例如 ADC）**little-endian**：低位元組在較小的位址，一次讀完就是 LOW、HIGH 的順序。
  同一筆讀取裡的輸入來自同一個快照（見「輸入」）。

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
  - Step 12-a 是 1.0（auto-increment 改了 transaction 規則，所以從 Step 11 算是 major 改變）；Step 12-b 加 ADC 與按鍵是 1.1：
    只用了原本讀 0xFF 的位址，認得 1.0 的 driver 照樣能用。
- **FW_MAJOR / FW_MINOR**（0x01 / 0x02）描述 firmware 本身：每次發佈都要改，protocol 沒變也一樣（例如只修 bug）。
