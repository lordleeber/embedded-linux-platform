# Phase 5 — STM32F103 自製 Peripheral

> Parent roadmap: `ROADMAP.md`

這是整條 roadmap 最重要的一個階段。

## 目的

從：

```text
Linux driver 控制別人做好的 IC
```

進一步變成：

```text
Linux driver + device firmware
全部自己寫
```

架構：

```text
Jetson
   │
   │ I2C
   ▼
STM32F103
```

Jetson：

```text
Linux driver
```

STM32：

```text
I2C slave firmware
```

## 自己設計 register map

例如：

```text
0x00 Device ID
0x01 Firmware Version
0x02 Status

0x10 ADC Value
0x11 Temperature
0x12 Button State

0x20 LED Control
0x21 Output Control

0x30 Watchdog Status
```

## STM32 實作

學習：

```text
I2C slave
interrupt
DMA
GPIO
ADC
timer
watchdog
```

## Linux 端實作

建立：

```text
edge_ctrl.c
```

讀：

```c
i2c_smbus_read_byte_data()
```

寫：

```c
i2c_smbus_write_byte_data()
```

## 完成標準

例如：

```bash
echo 1 > led
```

實際讓：

```text
Jetson Linux
    ↓
I2C
    ↓
STM32
    ↓
LED ON
```

---

<!-- STEP_PLAN_START -->
## Step 規劃

### Step 11 — STM32F103 I2C slave firmware

**目標**

把 STM32 變成自己設計的 peripheral。

**實作範圍**

- I2C slave
- Device ID
- firmware version
- read-only register
- LED control register
- firmware README


<!-- STEP_DETAIL_START -->
### 這一步到底要做什麼

這裡的 **I2C slave** 是指：

```text
Jetson Orin Nano = I2C controller/master
STM32F103        = I2C target/slave
```

Jetson 主動發起 transaction，STM32 不會自己隨意往 bus 上送資料。

先固定一個開發用 7-bit address，例如：

```text
STM32 address = 0x42
```

這只是本專案的 protocol address，不代表 STM32 固定只能用 0x42。

先做最小 register protocol：

```text
0x00  DEVICE_ID       read-only, 1 byte
0x01  FW_VERSION_MAJOR read-only, 1 byte
0x02  FW_VERSION_MINOR read-only, 1 byte
0x20  LED_CONTROL      read/write, 1 byte
```

例如：

```text
LED_CONTROL = 0 → LED OFF
LED_CONTROL = 1 → LED ON
其他值 → 回復/保留錯誤狀態，不要任意解讀
```

### Jetson 與 STM32 之間的 transaction

讀 register 的概念：

```text
Jetson START
  ↓
address 0x42 + WRITE
  ↓
send register address，例如 0x00
  ↓
REPEATED START
  ↓
address 0x42 + READ
  ↓
STM32 回 1 byte DEVICE_ID
  ↓
STOP
```

寫 LED：

```text
Jetson START
  ↓
0x42 + WRITE
  ↓
0x20
  ↓
0x01
  ↓
STOP
        ↓
STM32 設定 LED GPIO = ON
```

STM32 firmware 要有一個簡單 state machine，至少知道：

```text
目前選中的 register address
下一個 byte 是 data 還是 register index
read request 時要回哪個 register
```

如果使用 STM32Cube HAL，可以先用 interrupt/listen/address callback 類型的 I2C slave API，不要一開始做 DMA。

### 預期檔案

```text
firmware/stm32f103/
├── Core/
│   ├── Src/main.c
│   ├── Src/i2c_target.c
│   └── Inc/i2c_target.h
├── docs/register-map.md
└── README.md
```

### Jetson 端驗證方式

先找實際 bus：

```bash
i2cdetect -l
i2cdetect -y <bus>
```

應該看到 `0x42`。

再用 `i2cget/i2cset` 或一個極小 C++ tool 驗證：

```text
read 0x00 → 固定 DEVICE_ID
read 0x01/0x02 → firmware version
write 0x20 = 1 → STM32 板上 LED 亮
write 0x20 = 0 → LED 滅
```

### 實作決策（Step 11 落地時裁決）

- 誰和誰互動：Jetson（controller，`i2c-1` = `c240000.i2c`，header pin 27 SDA / 28 SCL，100 kHz）→ Blue Pill STM32F103C8T6 的 I2C1（target，PB7 SDA / PB6 SCL，7-bit 0x42）→ 板載 LED PC13（低電位亮）。Jetson 端只用 i2c-tools（`i2cget` / `i2cset` / `i2ctransfer`），沒有新的 C++ tool。bus 和 OLED 共用；Step 11 驗收時 OLED 拔掉（一支 header pin 只插得下一條線），驗收腳本看到 0x3c 就檢查它還在，沒看到就 SKIP
- 建置：照使用者 `STM32_StdPeriph` 課程（VS Code + PlatformIO）的做法，**不指定 `framework`**：PlatformIO 的 `framework-spl`（registry 上只有 2.10201.0）只有 F0 / F3 / F4 / L1，`framework = spl` 對 `bluepill_f103c8` 會報 `This board doesn't support spl framework`（ststm32 6.1.1 到 20.0.0 的 bluepill 板子設定都沒有 spl）。SPL V3.5.0 驅動（只收用到的 misc / gpio / i2c / rcc）、CMSIS、GCC startup 與 linker script 從課程 `31_Led_Blink`（`eadc71c`）原樣複製進 `firmware/stm32f103/`，SHA-256 在 `vendor.sha256`，`.gitattributes` 設 `-text` 保住 CRLF。放在 firmware 目錄裡而不是 `third_party/`：PlatformIO 專案要能整個目錄用 VS Code 打開
- Jetson 是 aarch64：課程用的 `toolchain-gccarmnoneeabi@1.70201.0`（GCC 7.2.1）沒有 linux_aarch64 套件，改釘 `1.120301.0`（GCC 12.3.1）；GCC 12 的 assembler 不收 `build_type = debug` 傳給 `.s` 的 `-g2`，所以是 release build。OpenOCD 釘 `tool-openocd@3.1200.7`，燒錄指令照課程（`transport select swd`）。ST-Link 插 Jetson，要先裝 PlatformIO 的 udev 規則
- 分層：`Core/Src/i2c_target.c` 是沒有任何 SPL 呼叫的 register state machine（`write_start` / `rx` / `tx` / `stop` 四個事件），host 端用 CMake 編進 `build/test_i2c_target`；`Core/Src/main.c` 只做 SPL 初始化與兩個中斷（EV：ADDR、RXNE、TXE、STOPF；ER：AF = 讀取結束的 NACK、BERR、ARLO、OVR）
- protocol：寫入的第 1 個 byte 是 pointer、第 2 個是資料、之後丟掉；讀取不 auto-increment（每個 byte 都是同一個 register）；pointer 保留到下次寫入。RO / 沒定義的 register 與 LED 值不是 0 / 1 的寫入：bus 上照樣 ACK，然後丟掉；沒定義的 register 讀到 0xFF。DEVICE_ID 0xED、版本 0.1
- 主迴圈不用 `__WFI()`：DBGMCU_CR.DBG_SLEEP 被斷電清掉之後，睡在 WFI 的 F1 讓 SWD 讀不到記憶體，無法再燒錄（見 baseline 踩坑）
- 規模（非空白行，和 Step 10-b / 10-c 同一種算法；不含 vendor 檔與文件）：PR 開出時 754 行，code review 修正後 **796 行**：產品碼 285（`main.c` 96、`i2c_target.c` 53、`i2c_target.h` 55、`stm32f10x_conf.h` 10、`platformio.ini` 47，其餘是 CMake、`.gitattributes`、`.gitignore`、`vendor.sha256`）、測試 407（C++ 172、Python 235）、驗收腳本 104。動工前估約 730
- 錯誤後周邊的復原（PR #17 code review）：`I2C1_ER_IRQHandler` 只清旗標，BERR / ARLO 之後沒有 SWRST 或重新初始化；若 BUSY 卡住（ES096），0x42 不會再 ACK，只能按 RESET。排進 Step 12-a，和 STATUS register 一起做（先能觀測錯誤，再處理復原）

### 從 Step 11 帶到後面的

- Step 12-a：多 byte 讀取（ADC_LOW / HIGH）需要定義 auto-increment；Step 11 實測 F103 在 TXE 驅動、BUF 一直開著時，對方 NACK 前預先放進 DR 的 byte 不會跑到下一次讀取（變異測試見 baseline），auto-increment 時要重新驗證：預先放的那個 byte 會讓 pointer 多前進一格
- Step 12-a：寫入失敗沒有回報管道（F103 硬體先 ACK），STATUS register 補上
- Step 13（**結案**，見 Step 13 的「從 Step 11 帶過來的」）：target 把 SDA / SCL 拉住時（Step 11 實測：B6 在麵包板上誤接 GND），Tegra controller 一直 `I2C transfer timed out`，同 bus 的 ina3221 / fusb301 一起讀不到；線放開之後 bus 自己恢復（第二次沒有 unbind / bind `c240000.i2c` 也恢復了）。driver 的錯誤路徑要考慮「整條 bus 都 timeout」：那不是這顆晶片的錯
- 未處理：F1 errata（ES096）的 I2C analog filter 讓 BUSY 卡住；Step 11 沒遇到

### 預期檔案（Step 11 實際）

```text
firmware/stm32f103/
├── platformio.ini、vendor.sha256、README.md、docs/register-map.md
├── Core/Src/main.c、Core/Src/i2c_target.c、Core/Inc/i2c_target.h、Core/Inc/stm32f10x_conf.h
└── Start/、Library/、startup/、ldscript/（vendor，原樣）
tests/test_i2c_target.cpp、tests/test_stm32_i2c_target.py
scripts/verify_stm32_i2c.sh
```

### 這一步不做

- 不做 ADC
- 不做 watchdog
- 不做 SPI
- 不做 DMA
- 不寫 Jetson kernel driver

這一步只證明：

```text
Jetson userspace
    ↓ I2C
STM32F103 firmware
    ↓
register protocol + LED
```
<!-- STEP_DETAIL_END -->

**驗收條件**

Jetson 使用 userspace I2C 可以：

```text
read Device ID
read FW version
write LED control
```

### Step 12-a — 正式 register map：分區、auto-increment、STATUS、版本規則

**目標**

把 Step 11 的 demo protocol 擴充成可以維護的 peripheral contract。這一步只處理 protocol 本身，不碰新的周邊，**不需要新接線**（接線同 Step 11）。

**規模目標**

```text
預估新增 code：600–750 lines（含測試與驗收腳本；Step 11 只有 4 個 register 就用了 796 行）
```

**實作範圍**

- 正式 register map 與分區
- PROTOCOL_VERSION
- 多 byte 讀取的 auto-increment
- STATUS register（不合法寫入、bus error 的回報與清除）
- WATCHDOG_STATUS placeholder
- BERR / ARLO 之後的周邊復原
- versioning rules


<!-- STEP_DETAIL_START -->
### 這一步到底要做什麼

Step 11 只有最小 4 個 register。這一步把它擴充成一個真正可維護的 peripheral register map，但先只放「protocol 本身」需要的 register；ADC 與按鍵這些輸入留給 Step 12-b。

建議把 register 分區：

```text
0x00–0x0F  identification / version
0x10–0x1F  sensor / input（Step 12-b 才填）
0x20–0x2F  output control
0x30–0x3F  health / watchdog
```

這一步要有的 register：

```text
0x00 DEVICE_ID
0x01 FW_MAJOR
0x02 FW_MINOR
0x03 PROTOCOL_VERSION
0x20 LED_CONTROL
0x30 STATUS
0x31 WATCHDOG_STATUS   （placeholder，Step 14–15 才有意義）
```

要明確定義：

- 每個 register 是 RO/RW
- byte width
- endian（這一步還沒有多 byte 的值，但規則要先寫，Step 12-b 的 ADC 照用）
- reset default
- invalid write 行為：寫 RO / 沒定義的 register、LED 寫 0 / 1 以外的值，要在 STATUS 留下哪個 bit
- STATUS 的清除方式（read-to-clear 或 write-1-to-clear，落地時裁決並寫進文件）
- protocol versioning：什麼改動要升 PROTOCOL_VERSION、什麼只升 FW 版本

### 從 Step 11 帶過來的

- 多 byte 讀取要定義 auto-increment。Step 11 實測 TXE 驅動、BUF 一直開著時，對方 NACK 前預先放進 DR 的 byte 不會跑到下一次讀取；auto-increment 時「預先放的那個 byte」會讓 pointer 多前進一格，要先寫出會紅的向量與硬體測試再實作
- 寫入失敗沒有回報管道（F103 硬體先 ACK）：由 STATUS 補上
- 錯誤後周邊的復原（PR #17 code review）：`I2C1_ER_IRQHandler` 只清旗標，BERR / ARLO 之後沒有 SWRST 或重新初始化；BUSY 卡住（ES096）時 0x42 不再 ACK，只能按 RESET。順序：先讓錯誤在 STATUS 看得到，再做復原。Step 11 沒有重現方法，這一步若仍找不到，就照實標「只有 host 向量、未實測」
- **結案（Step 12-a）**：auto-increment 只在 transaction 內有效、讀取不移動 pointer，預先放的 byte 從設計上就不影響下一次讀取（變異「讀取移動 pointer」實機紅）；寫入錯誤由 STATUS 的三個 bit 回報；`I2C1_ER_IRQHandler` 遇到 BERR / ARLO / OVR 設 BUS_ERROR、SWRST、重新設定 I2C1。重設程序用「每次讀取結束都重設」的測試用 firmware 實測（實機測試與驗收腳本全綠）；**真正的 bus error 仍沒有重現方法，偵測那一段未實測**

### 實作決策（Step 12-a 落地時裁決）

- 誰和誰互動：同 Step 11（Jetson `i2c-1` controller → Blue Pill I2C1 target 0x42 → PC13 LED），Jetson 端仍只用 i2c-tools，沒有新的 C++ tool；沒有新接線
- register map v1.0：0x00 DEVICE_ID、0x01 / 0x02 FW 0.2、0x03 PROTOCOL_VERSION 0x10、0x20 LED_CONTROL、0x30 STATUS（RW1C，reset 0x80）、0x31 WATCHDOG_STATUS（RO，固定 0）。分區照規劃，0x10–0x1F 留給 12-b
- auto-increment：讀寫都遞增、過 0xFF 回 0x00，但**只在同一筆 transaction 裡**；pointer 只由寫入的第 1 個 byte 設定，讀取（包括 TXE 預先取的那個 byte）不移動它。沒先寫 pointer 的讀取、寫完資料後 repeated START 的讀取，都從 pointer 開始。換來的代價：Jetson 不能「連續讀下去」接著上次的位置，每次都要從 pointer 開始
- 寫入：每個資料 byte 各自寫到下一個位址、各自檢查；Step 11 的「之後的 byte 丟掉」改掉了（所以算 protocol major 改變）
- STATUS：bit 0 RO_WRITE、1 UNMAPPED_WRITE、2 BAD_VALUE、3 BUS_ERROR、7 RESET，4–6 保留。**write-1-to-clear，不用 read-to-clear**：讀 0x2F 時 TXE 會順便取 0x30，那個 byte 不會送到 Jetson（變異「read-to-clear」實機紅：旗標在 Jetson 讀之前就被清掉）。讀取任何位址都不算錯誤，因為多 byte 讀取本來就會讀過 register 尾端
- 版本規則：PROTOCOL_VERSION 高 4 bit major（不相容）、低 4 bit minor（只增加）；FW 版本每次發佈都改。Step 11 的 firmware 讀 0x03 得 0xFF
- 錯誤中斷：BERR / ARLO / OVR → `i2c_target_bus_error()` + SWRST + `i2c1_regs_init()`（SWRST 清掉 I2C1 的全部 register，所以位址、ACK、中斷要重設）；AF 照舊是讀取的正常結束。ES096 建議的「把 SCL / SDA 切成 GPIO 打 clock」沒做
- 規模（非空白行，同 Step 11 的算法）：PR 開出時新增 545 行，code review 修正後 **566 行**：產品碼 143（`i2c_target.h` 57、`i2c_target.c` 46、`main.c` 40）、測試 361（C++ 197、Python 164）、驗收腳本 62。動工前估 600–750
- code review（PR #21，medium）8 項的分流：
  - 改 code：cursor 回到 pointer 只在 `read_start()` 做（`stop()` 不再做，同一條規則不寫兩次）；實機測試的 `setUp` 也把 LED 關掉；ER handler 的註解不再宣稱 SWRST 能處理 ES096
  - 改文件、加向量：bus error 沒有 rollback，出錯前的 byte（包括 pointer）已經生效，Jetson 重送整筆；所有可寫 register 重送都沒有副作用（之後加的也要維持）
  - 寫明是刻意的：驗收腳本開頭與結束寫 `0xff` 會連 RESET 一起清
  - 記進 baseline 的未實測：每次 BERR 都完整重設，同 bus 其他裝置的毛刺會不會讓 F103 的 BERR 亮、造成 0x42 短暫 NACK
  - 排到後面：ES096 的完整解法 → phase06 Step 14；唯讀規則改成一張表、「讀取時鎖住」與 TXE 預先取的衝突 → Step 12-b

### 預期檔案（Step 12-a 實際）

```text
firmware/stm32f103/Core/Inc/i2c_target.h、Core/Src/i2c_target.c、Core/Src/main.c（改）
firmware/stm32f103/docs/register-map.md、README.md（改）
tests/test_i2c_target.cpp、tests/test_stm32_i2c_target.py、scripts/verify_stm32_i2c.sh（改）
```

### 驗證

- host 向量（`build/test_i2c_target`）：auto-increment、pointer 跨 transaction、預先放 byte 的影響、每種不合法寫入對應的 STATUS bit、清除方式
- Jetson userspace test：逐一讀寫所有 register，對 invalid address / invalid value 做 negative test，並檢查 STATUS
- Step 11 的 400 次交替讀照樣全對（不回歸）

### 這一步不做

- 不做 ADC、按鍵（Step 12-b）
- 不做真正的 watchdog（Phase 6）
- 不寫 Linux kernel driver（Step 13）
- 不做 SPI transport
<!-- STEP_DETAIL_END -->

**驗收條件**

register map 文件定義完整（分區、RO/RW、寬度、endian、reset 值、錯誤行為、版本規則），Jetson 端可穩定讀寫所有 register，不合法的寫入能從 STATUS 看到。

### Step 12-b — ADC 與按鍵輸入

**目標**

在 Step 12-a 的 register map 上加入真正的輸入：ADC 值與按鍵狀態。

**規模目標**

```text
預估新增 code：450–650 lines（含測試與驗收腳本）
```

**實作範圍**

- ADC value（ADC_LOW / ADC_HIGH）
- button state
- 多 byte 值的一致性（兩個 byte 來自同一次轉換）
- FW 版本升級（照 12-a 的 versioning rules）


<!-- STEP_DETAIL_START -->
### 這一步到底要做什麼

把 sensor / input 區填起來：

```text
0x10 ADC_LOW
0x11 ADC_HIGH
0x12 BUTTON_STATE
```

ADC 超過 8-bit，不能模糊寫「ADC Value」，要明確定義兩個 byte 的順序與讀取方式：

- byte 順序照 12-a 寫下的 endian 規則
- 一次 2 byte 的 auto-increment 讀取，兩個 byte 必須來自同一次轉換，分兩次讀時的行為也要寫清楚
- ⚠ **「讀取時鎖住」會撞上 TXE 預先取的 byte**（PR #21 code review）：12-a 的 auto-increment 安全，完全是因為讀取沒有副作用。若做成「讀 ADC_LOW 時把 HIGH 鎖住」，讀 0x0F 的 1 個 byte 時 TXE 就會順便取 0x10、觸發鎖存，Jetson 卻沒讀到 LOW。鎖存的時機要選不靠「讀了哪個 byte」的做法（例如在 ADC 轉換完成時一次更新 LOW / HIGH 兩個 byte、更新過程中不讓 TXE 拿到一半），並寫出會紅的向量與實機測試（讀 0x0F 之後再讀 0x10 / 0x11）
- 12-a 的唯讀規則寫在 `read_only()` 與 `read_reg()` 的 switch 兩個地方（PR #21 code review）；加 ADC、按鍵時很容易漏改一邊，改成一張「位址 → 讀取來源、唯讀或可寫」的表
- 取樣方式（連續轉換或讀取時觸發）、解析度（F103 是 12-bit）與參考電壓寫進文件

按鍵：Blue Pill 的 GPIO 內部上拉可用（不像 Jetson header 經過 TXB0108），firmware 自己 debounce；BUTTON_STATE 的值與 bit 定義寫進 register map。

### 從 Step 12-a 帶過來的

- 「讀取時鎖住」會撞上 TXE 預先取的 byte；唯讀規則寫在兩處（PR #21 code review）
- **結案（Step 12-b）**：快照在讀取**開始**時拍（`read_start()`），和讀了哪幾個 byte 無關，TXE 預先取的 byte 不觸發任何事（實機測試「讀 0x0F 之後讀 0x10 / 0x11」）；`read_only()` 與 `read_reg()` 的兩個 switch 換成一張 `REGS[]` 表（位址、可不可寫、getter）

### 實作決策（Step 12-b 落地時裁決）

- 誰和誰互動：同 12-a（Jetson `i2c-1` controller → Blue Pill I2C1 target 0x42），Jetson 端仍只用 i2c-tools。新的資料來源在 MCU 內：ADC1 → 主迴圈 → `target.adc`；PA1 → SysTick 中斷 → `debounce_tick()` → `target.button` / `target.presses`；I2C 中斷讀快照
- register map v1.1（minor：只用了原本讀 0xFF 的位址）：0x10 ADC_LOW、0x11 ADC_HIGH（bit 3:0）、0x12 BUTTON_STATE（bit 0 PRESSED）、**0x13 BUTTON_PRESSES**（規劃沒有，加上它 Jetson 輪詢之間的短按才不會漏；8-bit、255 後回 0、唯讀、讀取不清除）。FW 0.3
- ADC：ADC1 channel 0 = PA0、ADC clock 72 MHz / 6 = 12 MHz、取樣 239.5 cycles（約 21 µs 一個值）、連續轉換、開機校正一次、不平均；參考電壓是 VDDA（Blue Pill 的 3.3 V）。主迴圈看到 EOC 就用**一次 16-bit store** 發佈到 `target.adc`
- 一致性：`i2c_target_read_start()` 把 ADC、按鍵狀態、計數一次複製成快照，這筆讀取的所有 byte 都從快照來。**不在「讀到哪個 byte」時鎖存**，所以 TXE 預先取的 byte 沒有副作用（12-a 的規則照舊）。分成兩筆讀 0x10、0x11 可能來自不同轉換，register map 寫「不要這樣讀」
- 按鍵：PA1 內部上拉、按下 = 低；SysTick 1 ms 取樣，電位連續 20 ms 不變才改變狀態（`debounce.c`，不碰硬體，host 向量測）。SysTick 的優先權和 I2C 同一個 preemption 等級，兩者不互相打斷，快照不會拿到更新到一半的 button / presses
- 驗收腳本的人手選項叫 `--no-touch`（規劃寫 `--no-press`；這一步除了按鍵還要移 A0 的線）
- **錯位的實機檢查要讓輸入跨過 0x800、且讓 ADC_HIGH 是第 3 個 byte**：分壓中點約 2068，從不跨 0x800，讀錯也看不出來；A0 浮接時在 1966–2156 之間跳，會跨。讀 2 byte 時，變異版 2000 次也 0 次錯位（推論：第 1 個 byte 一進 shift register 就 TXE，第 2 個 byte 幾乎同時取）；`w1 0x0f r3` 讓 ADC_HIGH 在第 1 個 byte 送完後（約 90 µs）才取，變異版 2000 次 1131 次錯位。驗收腳本多一步「A0 拔起來浮接」，用這個讀法讀 1000 次
- code review（PR #23，medium）8 項的分流：
  - 改 code：驗收腳本「按一次」的計數檢查先加 256 再取餘數（bash 的 `%` 保留負號，計數從 255 繞回 0 時會誤判）；`ADC_Cmd()` 之後等至少 1 µs 再校正（RM0008：ADON 之後至少兩個 ADC clock，datasheet 的 tSTAB 約 1 µs）；priority group 改在 `main()` 開頭設一次，SysTick 用 `NVIC_EncodePriority(NVIC_GetPriorityGrouping(), 1, 1)`（原本手算的 `(1 << 2) | 1` 只在 group 2 下成立；init 順序本身不影響，寫進去的是原始值）；實機測試的中位數移到迴圈外
  - 改文件：實機測試與 `--no-touch` 假設 A0 接在穩定的電壓（中點），浮接時兩個 ADC 實機測試會因雜訊失敗
  - 排到 phase06 Step 14：`write_reg()` 把其他可寫位址都當 STATUS 處理，加 HEARTBEAT 時要先改
  - 不改：開機時按著算一次按下（設計選擇，register map 已寫）；`REGS[]` 線性搜尋（每 byte 不到 1 µs，一個 byte 傳送約 90 µs）
- 規模（非空白行，不含原樣收錄的 `stm32f10x_adc.c/.h`）：PR 開出時新增 631 行（另刪 82），code review 修正後 **659 行**：產品碼 205（`main.c` 73、`i2c_target.c` 57、`debounce.h` 26、`debounce.c` 24、`i2c_target.h` 23、`stm32f10x_conf.h` 2）、測試 331（`test_stm32_i2c_target.py` 141、`test_debounce.cpp` 97、`test_i2c_target.cpp` 93）、驗收腳本 119、CMake / ini 4。動工前估 450–650

### 預期檔案（Step 12-b 實際）

```text
firmware/stm32f103/Core/Inc/debounce.h、Core/Src/debounce.c（新）
firmware/stm32f103/Library/stm32f10x_adc.c、stm32f10x_adc.h（新，SPL 原樣收錄，vendor.sha256 加兩行）
firmware/stm32f103/Core/Inc/i2c_target.h、stm32f10x_conf.h、Core/Src/i2c_target.c、Core/Src/main.c、platformio.ini（改）
firmware/stm32f103/docs/register-map.md、README.md（改）
tests/test_debounce.cpp（新）、tests/test_i2c_target.cpp、tests/test_stm32_i2c_target.py、scripts/verify_stm32_i2c.sh、CMakeLists.txt（改）
```

### 接線（Step 12-b 實際）

- 麵包板上兩顆 330 Ω 串聯，從 Blue Pill 的 **3.3** 到 **G**（不用 VBT：那是 VBAT 的輸入）；A0 的線插在兩顆電阻的接點（中點），驗收時移到 G、3.3、拔起來浮接，最後插回中點
- 兩腳按鍵：A1 → 按鍵 → G，不接外部電阻（PA1 內部上拉）

### 接線（新增）

- ADC 輸入：可變電阻或分壓接到一支 ADC pin（例如 PA0），兩端接 Blue Pill 的 3.3 V 與 GND；驗收用接 GND / 接 3.3 V 兩個端點值
- 按鍵：一支 GPIO（例如 PA1）→ 按鍵 → GND
- 實際 pin 落地時決定，寫進 README 與 register map

### 驗證

- host 向量：ADC 兩個 byte 的鎖存、byte 順序、按鍵 debounce
- Jetson userspace test：ADC 接 GND 時接近 0、接 3.3 V 時接近 4095（容差落地時定）；按鍵按下 / 放開（要有人按，同 Step 5 的做法提供 `--no-press`）
- Step 12-a 的全部 register 測試不回歸

### 這一步不做

- 不寫 Linux kernel driver（Step 13）
- 不做 SPI transport
- 不做按鍵的中斷通知 Jetson（target 不能主動發 I2C；之後若需要另接 GPIO）
- 不做 DMA
<!-- STEP_DETAIL_END -->

**驗收條件**

protocol 有明確文件，Jetson 端可穩定讀寫多個 register，ADC 兩個 byte 一致、按鍵狀態正確。

### Step 13 — Jetson edge_ctrl I2C driver

**目標**

把 STM32 peripheral 接入 Linux kernel。

**實作範圍**

- `edge_ctrl.c`
- I2C driver
- DT node
- read/write attributes
- firmware version/status exposure


<!-- STEP_DETAIL_START -->
### 這一步到底要做什麼

前兩步是 Jetson userspace 直接操作 I2C。這一步把 STM32 register protocol 包進 Linux I2C driver，讓 application 不再知道 `/dev/i2c-*` 與 raw register transaction。

Device Tree：

```dts
controller@42 {
    compatible = "edge,controller";
    reg = <0x42>;
};
```

driver：

```text
edge_ctrl.c
  ├── probe()
  ├── remove()
  ├── read_reg()
  ├── write_reg()
  └── status exposure
```

至少 expose：

```text
device_id
firmware_version
adc
button
led control
status
```

可以先用 sysfs 或 character device；但要在 roadmap/README 寫清楚為什麼選這個 interface。

### 驗證

比對：

```text
userspace raw I2C tool 結果
vs
kernel driver exposed value
```

兩者必須一致。

### 這一步不做

- 不做 heartbeat
- 不做 `poll()`

### 從 Step 11 帶過來的

- 「整條 bus 都 timeout 不是這顆晶片的錯」：**結案（Step 13）**。每次存取的 errno 原樣回給 userspace，driver 不留「壞掉」的狀態、不在每次存取時印 log（tegra-i2c 自己會印），下一次存取直接重試。實測的是 Blue Pill 斷電（拔 ST-Link）：讀取回 `Remote I/O error`、同 bus 的 ina3221 照樣讀到 `0x4954`，插回後不用 unbind / bind 就恢復；**SCL 被拉住、整條 bus timeout 的情況沒有重現**（要把線接到 GND，沒做），只由原始碼測試守住「錯誤路徑不留狀態」

### 實作決策（Step 13 落地時裁決）

- 誰和誰互動：Jetson `i2c-1`（`c240000.i2c`）controller → Blue Pill I2C1 target 0x42（firmware 不變，仍是 12-b 的 FW 0.3 / map 1.1）。新的一層在 Jetson kernel：`edge_ctrl.ko`（I2C client driver）把 register protocol 包成 client 目錄下的 sysfs 屬性；application 讀寫檔案，不碰 `/dev/i2c-1`
- **interface 選 sysfs**（規劃讓 sysfs 或 character device 二選一）：規劃的實作範圍寫「read/write attributes」；這些值都是「現在是多少」的狀態，一個值一個檔、`cat` / `echo` 就能用，沒有串流或事件；也不是 hwmon 的類別（ADC 是任意電壓的原始值）。Step 19 的 `poll()` 要 wait queue 與 event 語意，phase08 規劃的是 `/dev/edge_ctrl`，到時再加 character device。理由也寫在 `kernel/edge_ctrl/README.md`
- 屬性：`device_id`、`firmware_version`、`protocol_version`、`adc`、`button`、`button_presses`（0444）；`led`、`status`（0644，sysfs 不允許 others 寫，所以寫入要 root）。用 `.driver.dev_groups`，屬性跟著綁定出現與消失。不 expose WATCHDOG_STATUS（Phase 6 才有意義）
- compatible `edge,edge-ctrl`（規劃寫 `edge,controller`）：client 名稱是 compatible 去掉前綴，避開 `controller` 這種通用字（Step 7 的教訓）；節點名照規劃 `controller@42`，放在 overlay 新的 `fragment@6`（`&gen2_i2c`，和 `oled@3c` 同一個 bus，但分開一個 fragment）
- `read_reg()` 是一個 `i2c_transfer()`（寫 pointer + repeated START + 讀 N byte）：adapter 鎖住整筆，同 bus 的其他使用者插不進來移動 pointer；一筆讀取的所有 byte 來自 firmware 同一個快照，所以 `adc` 一次讀 2 byte、`firmware_version` 一次讀 0x01–0x02。部分完成的 transfer 算 `-EIO`
- probe 一次讀 0x00–0x03：DEVICE_ID ≠ 0xED 或 PROTOCOL_VERSION 不是 1.x（x ≥ 1）就 `-ENODEV`，照 register map 的版本規則；STATUS 只讀出來印在 dmesg，不清（RESET 旗標留給讀的人）
- `led` 寫入只收 0 / 1，其他值在 driver 就回 `EINVAL`、不送上 bus：firmware 對錯誤值照樣 ACK、只在 STATUS 記 BAD_VALUE，不先擋的話寫的人看到的是成功。`edge_ctrl_led_ok()` 與 firmware 接受的值由向量逐值（0–255）比對
- register 位址與解碼放在 `include/edge_ctrl_regs.h`（kernel 不能 include firmware 那份用 `<stdint.h>` 的 `i2c_target.h`）；`build/test_edge_ctrl_regs` 把 firmware 的 `i2c_target.c` 一起編進來，用 driver 的 transaction 驅動它，再用 header 的 helper 解碼：期望值來自 firmware 的實作，不是 header 自己
- 「userspace raw vs kernel driver 一致」：device 測試用 `i2ctransfer -f`（driver 綁定時 i2c-dev 不加 `-f` 是 `EBUSY`）。識別、版本、按鍵、STATUS 逐字相同；ADC 兩邊各讀 20 次、中位數差 ≤ `ADC_SPREAD_MAX`（40，沿用 Step 12-b）
- code review（PR #25，medium）6 項的分流：
  - 改 code：probe 先 `i2c_check_functionality(client->adapter, I2C_FUNC_I2C)`，不支援時 `-EOPNOTSUPP`；驗收腳本先確認 `status` 讀到的是 hex 再做算術；device 測試「不合法的 LED 值沒送上 bus」只看三個寫入被丟掉的 bit（不看 RESET / BUS_ERROR）
  - 改註解：`EDGE_CTRL_ADDR`、`EDGE_CTRL_REG_FW_MINOR` 只給向量用（driver 的位址來自 DT 的 `reg`）
  - 不改：show 函式的樣板（1 byte 的用 `read_u8()`，要一筆讀 2 byte 的直接 `read_reg()`，是刻意的）；超過大小上限（不事後拆，已記錄）
- 規模（非空白行，不含 .md）：PR 開出時 978 行，code review 修正後 **999 行**，超過 800 的上限；動工前**沒有寫下估計**（違反 CLAUDE.md 的規則），寫完才量到。修正後 driver 208、header 48、測試 509（static 238、C++ 146、device 122、12-b 的範圍檢查 3）、驗收腳本 202、overlay / Makefile / CMake 32。數字見 `docs/baseline.md`

### 預期檔案（Step 13 實際）

```text
kernel/edge_ctrl/edge_ctrl.c、Makefile、README.md（新）
include/edge_ctrl_regs.h（新）
dts/edge-gpio-overlay.dts（改：fragment@6 controller@42）
tests/test_edge_ctrl_regs.cpp、tests/test_edge_ctrl_static.py、tests/test_edge_ctrl_device.py（新）
scripts/verify_edge_ctrl.sh（新）
CMakeLists.txt、tests/test_stm32_i2c_target.py（改：12-b 的範圍檢查拿掉「沒有 kernel/edge_ctrl」）
```
<!-- STEP_DETAIL_END -->

**驗收條件**

```text
Jetson Linux driver
  ↓ I2C
STM32 firmware
  ↓
GPIO / ADC / status
```

整條 path 可工作。
<!-- STEP_PLAN_END -->
