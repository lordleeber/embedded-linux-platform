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

### Step 12 — 自訂 register map + ADC / GPIO

**目標**

把 protocol 從 demo 擴充成可用 peripheral contract。

**實作範圍**

- 正式 register map
- ADC value
- button state
- status
- watchdog status placeholder
- versioning rules


<!-- STEP_DETAIL_START -->
### 這一步到底要做什麼

Step 11 只有最小 4 個 register。這一步才把它擴充成一個真正可維護的 peripheral register map。

建議把 register 分區：

```text
0x00–0x0F  identification / version
0x10–0x1F  sensor / input
0x20–0x2F  output control
0x30–0x3F  health / watchdog
```

例如：

```text
0x00 DEVICE_ID
0x01 FW_MAJOR
0x02 FW_MINOR
0x03 PROTOCOL_VERSION
0x10 ADC_LOW
0x11 ADC_HIGH
0x12 BUTTON_STATE
0x20 LED_CONTROL
0x30 STATUS
0x31 WATCHDOG_STATUS
```

要明確定義：

- 每個 register 是 RO/RW
- byte width
- endian
- reset default
- invalid write 行為
- protocol versioning

ADC 若超過 8-bit，不能模糊寫「ADC Value」，要明確定義兩個 byte 或 multi-byte read 的順序。

### 驗證

建立一個 Jetson userspace test，逐一讀寫所有 register，並對 invalid address / invalid value 做 negative test。

### 這一步不做

- 不寫 Linux kernel driver
- 不做 SPI transport
<!-- STEP_DETAIL_END -->

**驗收條件**

protocol 有明確文件，Jetson 端可穩定讀寫多個 register。

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
