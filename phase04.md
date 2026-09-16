# Phase 4 — OLED Driver

> Parent roadmap: `ROADMAP.md`

## 目的

從「讀 sensor」進一步練習「控制 peripheral」。

假設 OLED controller 是：

```text
SSD1306
```

或相似控制器。

硬體：

```text
Jetson
   │
  I2C
   │
 OLED
```

## 實作內容

自己處理：

```text
OLED initialization sequence
command mode
data mode
screen buffer
pixel drawing
character rendering
```

建立 driver：

```text
edge_oled.c
```

## 初期不必追求 framebuffer subsystem

可以先做簡單 API：

```text
/sys/.../text
```

或：

```text
/dev/edge_oled
```

userspace：

```bash
echo "EDGE" > /dev/edge_oled
```

## 完成標準

OLED 顯示：

```text
EDGE

BAT: 87%
V: 11.9V
I: 1.8A
P: 21W
```

資料來源使用上一階段 INA219。

---

<!-- STEP_PLAN_START -->
## Step 規劃

### Step 9 — OLED userspace protocol proof

**目標**

先證明 SSD1306 command/data sequence 與 I2C 通訊正確。

**實作範圍**

- initialization sequence
- clear screen
- draw pixel
- 顯示固定字串
- userspace prototype


<!-- STEP_DETAIL_START -->
### 這一步到底要做什麼

在寫 OLED kernel driver 前，先用 userspace 確認這片 OLED 到底是不是 SSD1306 相容、I2C address 是多少、初始化 sequence 是否正確。

userspace prototype 要能：

1. `i2cdetect` 找到 OLED
2. 送 display off/on command
3. 設定 addressing mode
4. clear display RAM
5. 畫單一 pixel / pattern
6. 顯示固定圖案或固定字串

要理解 SSD1306 I2C 傳輸中：

```text
control byte
command byte(s)
data byte(s)
```

不是單純把 ASCII `"HELLO"` 寫進 I2C 就會顯示。

### 預期檔案

```text
tools/oled_probe.cpp
docs/ssd1306-notes.md
```

### 驗證

至少要做到 power-cycle 後程式仍可重新初始化 OLED，不依賴「前一次剛好留下的狀態」。
<!-- STEP_DETAIL_END -->

**驗收條件**

OLED 穩定顯示固定的 `EDGE`。

### Step 10-a — OLED kernel driver skeleton

**目標**

先把 OLED 從 userspace prototype 移到最小 kernel-facing device path，不處理完整文字排版。

**規模目標**

```text
預估新增 code：250–450 lines
```

**實作範圍**

- `edge_oled.c`
- I2C probe/remove
- OLED init / clear
- 最小 `/dev/edge_oled` 或 sysfs API
- 寫入 raw / fixed-size display buffer
- basic error handling


<!-- STEP_DETAIL_START -->
### 這一步到底要做什麼

把 Step 9 已驗證的 SSD1306 command/data sequence 移到 kernel I2C driver。這一步只建立 transport + device lifecycle，不急著做完整文字 rendering。

driver 要處理：

```text
probe()
  ↓
初始化 display
  ↓
配置 shadow/frame buffer
  ↓
提供最小 userspace entry
  ↓
remove()
```

最小 userspace entry 可以先支援：

```text
clear
fill
raw framebuffer write
```

### 實作重點

- I2C transfer error 要往上回報
- 不要在 probe 裡無限 retry
- buffer ownership 要明確
- remove 時取消 pending work
- display size 128x64/128x32 要固定成你實際硬體

### 這一步不做

- 不實作 font table
- 不顯示 battery telemetry
<!-- STEP_DETAIL_END -->

**驗收條件**

kernel driver 載入後，可以從 userspace 觸發 clear screen 與固定 pattern 顯示。

### Step 10-b — OLED text buffer + font rendering

**目標**

只處理文字 rendering，不同時加入 telemetry policy。

**規模目標**

```text
預估新增 code：300–550 lines
```

**實作範圍**

- text buffer
- minimal bitmap font
- character rendering
- line / column positioning
- clipping / invalid character handling


<!-- STEP_DETAIL_START -->
### 這一步到底要做什麼

這一步只做「字元如何轉成 OLED pixel」。把 rendering 和 I2C transport 分開，避免 driver 變成一個巨大混合物。

建立最小 bitmap font，例如：

```text
5x7 或 6x8 ASCII
```

需要定義：

```text
draw_pixel(x, y)
draw_char(x, y, c)
draw_string(x, y, text)
clear()
```

要處理：

- x/y 超出範圍
- 不支援字元
- newline
- 一行太長
- framebuffer → OLED page layout 的 mapping

### 驗證

使用固定測試字串：

```text
ABCDEFGHIJKLMNOPQRSTUVWXYZ
0123456789
EDGE
```

確認字元不左右顛倒、上下顛倒、跨 page 錯位。

### 這一步不做

- 不讀 INA219
- 不做 periodic timer
<!-- STEP_DETAIL_END -->

**驗收條件**

可以顯示多行文字：

```text
EDGE
LINE 2
123456
```

### Step 10-c — INA219 telemetry display app

**目標**

把前一階段 hwmon 資料接到 OLED，但不再修改 OLED driver 核心。

**規模目標**

```text
預估新增 code：200–400 lines
```

**實作範圍**

- 讀取 hwmon voltage/current/power
- format telemetry
- periodic refresh
- stale/error display
- clean shutdown


<!-- STEP_DETAIL_START -->
### 這一步到底要做什麼

建立一個 userspace telemetry application，把 hwmon 資料格式化後送到 OLED。這一步刻意放在 userspace，避免把「電池顯示策略」塞進 kernel driver。

資料流：

```text
INA219
  ↓
edge_ina219 kernel driver
  ↓
hwmon sysfs
  ↓
telemetry_display app
  ↓
/dev/edge_oled
  ↓
OLED
```

建議畫面：

```text
V: 11.92 V
I:  1.84 A
P: 21.93 W
```

app 要處理：

- 固定 refresh interval，例如 500 ms 或 1 s
- sysfs read failure
- stale value
- OLED write failure
- SIGINT/SIGTERM clean shutdown

### 這一步不做

- 不做 low-battery policy
- 不做 network notification
<!-- STEP_DETAIL_END -->

**驗收條件**

OLED 可持續顯示：

```text
BAT / Voltage / Current / Power
```

<!-- STEP_PLAN_END -->
