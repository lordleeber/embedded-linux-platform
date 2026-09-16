# Phase 2 — GPIO + LED + Interrupt

> Parent roadmap: `ROADMAP.md`

## 目的

第一次讓 Linux kernel driver 控制真實硬體。

## 硬體

```text
Jetson GPIO
   │
   ├── LED
   └── Button
```

## 實作

建立：

```text
edge_gpio_driver
```

學習：

- GPIO descriptor API
- platform driver
- Device Tree
- GPIO interrupt
- IRQ handler
- wait queue
- blocking read

設計：

```text
Button
   ↓
GPIO
   ↓
IRQ
   ↓
kernel driver
   ↓
wake_up_interruptible()
   ↓
userspace read() 醒來
```

## 完成標準

按下實體按鈕：

```text
kernel IRQ
    ↓
userspace event
    ↓
LED 切換狀態
```

---

<!-- STEP_PLAN_START -->
## Step 規劃

### Step 4 — GPIO output + Device Tree

**目標**

第一次讓自己的 kernel driver 控制實體 LED。

**實作範圍**

- platform driver
- GPIO descriptor API
- Device Tree node
- `probe()` / `remove()`
- userspace control interface


<!-- STEP_DETAIL_START -->
### 這一步到底要做什麼

這一步第一次讓 Device Tree 描述真實硬體，讓 kernel driver 透過 `probe()` 拿到一根 GPIO 並控制 LED。

Device Tree 應描述：

```text
compatible
GPIO controller
pin number
active high / active low
```

driver 使用 descriptor-based GPIO API，而不是舊式 global GPIO number API：

```text
devm_gpiod_get()
gpiod_set_value_cansleep()
```

資料流：

```text
Device Tree node
      ↓
platform bus match compatible
      ↓
driver probe()
      ↓
取得 GPIO descriptor
      ↓
userspace command
      ↓
LED ON/OFF
```

### 預期檔案

```text
kernel/edge_gpio/
├── edge_gpio.c
└── Makefile

dts/
└── edge-gpio-overlay.dts
```

### 驗證

- `probe()` 確實由 DT match 觸發
- 移除 DT node 後 driver 不應憑空 probe
- LED active-low/active-high 行為正確
- unload driver 後 GPIO 被釋放

### 這一步不做

- 不加入 IRQ
- 不做 button
<!-- STEP_DETAIL_END -->

**驗收條件**

```text
Device Tree
  ↓
probe()
  ↓
GPIO acquired
  ↓
userspace command
  ↓
LED ON/OFF
```

### Step 5 — GPIO IRQ + blocking read

**目標**

讓實體 button event 從硬體一路喚醒 userspace。

**實作範圍**

- GPIO input
- IRQ registration
- IRQ handler
- wait queue
- blocking `read()`
- event counter / debounce 基礎


<!-- STEP_DETAIL_START -->
### 這一步到底要做什麼

把 GPIO 從 output 擴充成 input + interrupt。目標不是「讀 GPIO 值」，而是讓 userspace 可以睡眠等待事件，不需要一直輪詢。

driver 要完成：

```text
GPIO input
  ↓
gpiod_to_irq()
  ↓
request_threaded_irq() 或 devm_request_threaded_irq()
  ↓
IRQ handler
  ↓
記錄 event
  ↓
wake_up_interruptible()
  ↓
blocking read() 返回
```

userspace 行為應該是：

```c
read(fd, &event, sizeof(event));
```

沒有按鍵時這個 `read()` 要 block，而不是 CPU 100% busy loop。

### 要處理的細節

- rising/falling edge 選擇
- debounce 最小策略
- IRQ handler 不能做會 sleep 的重工作
- event lost / repeated event 的行為要定義
- driver unload 時要喚醒或安全終止等待者

### 驗證

用實體 button 做至少：

```text
按一下 → 一個 event
長按 → 行為可預期
快速連按 → 不造成 kernel crash
```

### 這一步不做

- 不做 `poll()`
- `poll()` 留到 Phase 8
<!-- STEP_DETAIL_END -->

**驗收條件**

按下 button 後：

```text
IRQ
 ↓
driver
 ↓
wake_up_interruptible()
 ↓
blocked userspace read() returns
```
<!-- STEP_PLAN_END -->
