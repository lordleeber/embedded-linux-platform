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
- Step 13：target 把 SDA / SCL 拉住時（Step 11 實測：B6 在麵包板上誤接 GND），Tegra controller 一直 `I2C transfer timed out`，同 bus 的 ina3221 / fusb301 一起讀不到；線放開之後 bus 自己恢復（第二次沒有 unbind / bind `c240000.i2c` 也恢復了）。driver 的錯誤路徑要考慮「整條 bus 都 timeout」：那不是這顆晶片的錯
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
- 一次 2 byte 的 auto-increment 讀取，兩個 byte 必須來自同一次轉換（例如讀 ADC_LOW 時把 HIGH 鎖住），分兩次讀時的行為也要寫清楚
- 取樣方式（連續轉換或讀取時觸發）、解析度（F103 是 12-bit）與參考電壓寫進文件

按鍵：Blue Pill 的 GPIO 內部上拉可用（不像 Jetson header 經過 TXB0108），firmware 自己 debounce；BUTTON_STATE 的值與 bit 定義寫進 register map。

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
