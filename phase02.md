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

### Step 4-a — userspace GPIO output（C++ GPIO v2 uAPI）

**目標**

先不寫 kernel driver，在 userspace 確認 header pin 29 的 LED 真的能被點亮，把「電路、pad、GPIO line」三件事和 driver 分開驗證。

**規模目標**

```text
預估新增 code：350–450 lines（含測試與驗收腳本）
```

**實作範圍**

- 最精簡的 C++ 程式（無參數，固定 gpiochip0 line 105 閃 5 次）直接用 GPIO character device v2 uAPI（`GPIO_V2_GET_LINE_IOCTL`、`GPIO_V2_LINE_SET_VALUES_IOCTL`），不依賴 libgpiod
- pad 設定腳本：以 `/dev/mem` 讀寫 PQ.05 的 pinmux 暫存器（實驗用）
- 驗收腳本


<!-- STEP_DETAIL_START -->
### 這一步到底要做什麼

JP6（L4T R36）開機時 pin 29 的 pad（`soc_gpio32_pq5`）是 tristate：GPIO controller 的 output register 寫成 1，電壓也到不了腳位。Step 4 原計畫直接做 kernel driver，實測時 driver 一切正常，LED 卻不亮，所以拆出這一步，先在 userspace 把問題分層。

誰和誰互動：

```text
edge_gpio_blink (C++, userspace)
   │ open + ioctl
   ▼
/dev/gpiochip0 ── gpiolib ── gpio-tegra186 ── GPIO controller（line 105 = PQ.05）
                                                   │
pad_pin29.py ── /dev/mem ── pinmux 暫存器 0x02430068 ┘ pad：tristate / input / pull
                                                   │
                                            header pin 29 ── 電阻 ── LED ── pin 30 GND
```

- controller：Jetson 這端的 userspace 程式；target：GPIO controller 與 pad
- `edge_gpio_blink` 請求 line 105 為 output、閃爍、最後寫 0 再釋放
- `pad_pin29.py` 先讀暫存器、確認低位元組是預期值（`0x58` 開機值或 `0x00` 已開啟）才寫；`open` 清掉 tristate / input / pull，`close` 還原開機值

### 預期檔案

```text
apps/edge_gpio_blink.cpp
scripts/pad_pin29.py
scripts/verify_edge_gpio_blink.sh
tests/test_edge_gpio_blink.py
tests/test_pad_pin29.py
```

### 驗證

- line 被佔用時第二個程式請求失敗（結束碼 1、stderr 顯示 busy）
- line 105 被持有時 `gpioinfo` 顯示 consumer 與 output；結束後釋放
- pad 腳本在假的 mem 檔上驗：解碼、open/close、低位元組不符時拒寫
- 實機：pad 開啟前 LED 不亮；開啟後 debugfs 讀到 hi/lo 且 LED 亮滅（人眼）；結束後 pad 還原

### 這一步不做

- 不寫 kernel driver、不改 Device Tree（Step 4-b）
- 不把 devmem 當正式做法；pad 的正式設定交給 4-b 的 DT pinctrl
- 不加入 IRQ、不做 button
<!-- STEP_DETAIL_END -->

**驗收條件**

```text
pad open (devmem)
  ↓
edge_gpio_blink 請求 line 105
  ↓
LED ON/OFF（人眼）
  ↓
line 釋放、LED 熄、pad 還原
```

### Step 4-b — GPIO output + Device Tree（kernel driver）

**目標**

第一次讓自己的 kernel driver 控制實體 LED。

**實作範圍**

- platform driver
- GPIO descriptor API
- Device Tree node（含 pad 的 pinctrl 狀態）
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
pad 狀態（pinctrl-0：關掉 tristate，取代 4-a 的 devmem）
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
├── edge-gpio-overlay.dts
└── Makefile                          （cpp + dtc，產出 active-high / active-low 兩個 dtbo）

scripts/install_edge_gpio_overlay.py  （把 overlay 加進 extlinux.conf 的 DEFAULT label）
scripts/verify_edge_gpio.sh           （驗收：有 / 沒有 DT node 兩種模式）
tests/test_edge_gpio_static.py
tests/test_install_overlay.py
tests/test_edge_gpio_device.py
```

### 驗證

- `probe()` 確實由 DT match 觸發
- 移除 DT node 後 driver 不應憑空 probe
- LED active-low/active-high 行為正確（active-high 已實測；active-low 只有靜態測試，未改接線實測）
- unload driver 後 GPIO 被釋放
- driver 載入期間 4-a 的 `edge_gpio_blink` 請求 line 105 得到 busy
- 順帶修正（4-a code review 發現、範圍外延後）：`verify_edge_test.sh` 與 `verify_edge_gpio.sh` 以 root 寫入 `/tmp/<name>.$$`，改用 `mktemp`；`verify_edge_gpio.sh` 的 pinconf 解析改成多行格式

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
