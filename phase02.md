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

### Step 5-a — userspace GPIO input + edge event（C++ GPIO v2 uAPI）

**目標**

不寫 kernel driver，用 GPIO character device 的 edge event 在 userspace 等按鍵：`read()` 一樣會睡、一樣有 debounce。和 5-b 對照：5-b 親手寫的 IRQ handler、佇列、wait queue，這裡由 kernel 的 `gpiolib-cdev` 代勞。

**實作範圍**

- C++ 程式直接用 GPIO v2 uAPI（不依賴 libgpiod）：請求 gpiochip0 line 43（pin 33）為 input，`GPIO_V2_LINE_FLAG_EDGE_RISING | GPIO_V2_LINE_FLAG_EDGE_FALLING`，`GPIO_V2_LINE_ATTR_ID_DEBOUNCE` 設 debounce
- 對 line request fd 做 blocking `read()`，拿到 `struct gpio_v2_line_event`（`timestamp_ns`、`id`、`seqno`）
- 驗收腳本與測試

<!-- STEP_DETAIL_START -->
### 這一步到底要做什麼

拆分紀錄：原 Step 5 先做成 kernel 版（現在的 5-b），驗收後使用者指出這件事完全可以在 userspace 做，kernel 版是為了教學。所以補這一步當對照，學習順序上排在 5-b 前面（和 4-a / 4-b 同一個形狀：先 userspace、再 kernel）。

誰和誰互動：

```text
userspace 程式 ── ioctl(GPIO_V2_GET_LINE_IOCTL) ──▶ gpiolib-cdev
     ▲                                                │ IRQ handler、kfifo、wait queue（kernel 內建）
     └──────── read(line fd) 回 gpio_v2_line_event ◀──┘
                                                      │
                     GPIO controller（line 43 = PH.00）◀─ TXB0108 ◀─ pin 33 ◀─ 按鍵 / 330 Ω 上拉
```

- 硬體與接線沿用 5-b（pin 33 → 按鍵 → pin 34，330 Ω 上拉到 pin 1）
- 先確認：沒有 `edge_button` driver probe（pinctrl 狀態沒被套用）時，pin 33 的開機預設 pad 能不能讀到按鍵；不能的話要記錄並決定怎麼設 pad

### 這一步不做

- 不寫 kernel driver、不改 Device Tree
- 不做 `poll()`（Phase 8）
<!-- STEP_DETAIL_END -->

**驗收條件**

```text
按下 button
  ↓
gpiolib-cdev（kernel 內建）
  ↓
blocked userspace read(line fd) returns gpio_v2_line_event
```

### Step 5-b — GPIO IRQ + blocking read（kernel driver）

**目標**

讓實體 button event 從硬體一路喚醒 userspace，IRQ handler、debounce、wait queue 由我們的 driver 親手實作。

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

### 實作決策（Step 5-b 落地時裁決）

- 接線：header pin 33（GPIO13，PH.00，gpiochip0 line 43，DT cell 56）→ 按鍵 → pin 34（GND），兩支 pin 左右相鄰，按鍵直接跨上去（原本選 pin 31 只因它和 LED 的 PQ.05 同一個 port，但實體上和 34 是斜對角）。DT 用 `GPIO_ACTIVE_LOW`，邏輯 1 = 按下；pad 的 pinctrl 狀態設 tristate（pad 不輸出，按下時不會短路）、enable-input。上拉要外接 330 Ω～1 kΩ 到 3.3 V（pin 1）：pin 33 在載板上經 TXB0108，SoC 內部上拉拉不到 header 這側（實測恆為 0）；TXB 的 ~4 kΩ buffer 會保持上一次的電位，上拉要遠小於 4 kΩ 才拉得回高電位，51 kΩ／10 kΩ 都不行。這和規格書「上拉 > 50 kΩ」相反，那條規定是保護 pin 當輸出時的電位，按鍵 pin 只當輸入。
- 獨立 module `kernel/edge_button`（compatible `edge,gpio-button`，`/dev/edge_button`），不改 Step 4 的 `edge_gpio`；DT 節點加在同一份 overlay 的 `fragment@2/3`，沿用同一支 installer。
- IRQ：`devm_request_irq()` 雙邊緣觸發，hard IRQ handler 只計數並 `mod_delayed_work()`（不讀 GPIO、不睡）；debounce 用 gpio-keys 的做法：最後一個邊緣後 20 ms 才在 work 裡讀電位，狀態有變才產生事件。debounce 本身就要延遲，所以用 delayed work 取代 threaded IRQ。
- 事件格式 `include/edge_button.h`：`u64 timestamp_ns`、`u32 seq`、`u32 pressed`，16 bytes；`read()` 一次回一筆，buffer 小於 16 回 `EINVAL`，`O_NONBLOCK` 沒事件回 `EAGAIN`。
- 事件語意：按一下 = pressed + released 兩筆；長按不重複；佇列 16 筆，滿了丟新事件並累加 `dropped`，`seq` 照算，所以 seq 跳號 = 遺失。只允許一個 reader（第二個 open 回 `EBUSY`），open 時清空佇列，關著時不排事件。
- unload：檔案開著時 `.owner` 讓 rmmod 被拒，所以 remove 時不可能有等待者；等待者靠 signal 離開（`wait_event_interruptible`）。`suppress_bind_attrs` 擋掉 sysfs unbind。
- sysfs 計數器 `irq_count`（原始邊緣數，含彈跳）、`event_count`、`dropped`，掛在 platform device 上，驗收時用來看彈跳被合併了多少。

### 預期檔案

```text
include/edge_button.h                 （事件格式，kernel / userspace 共用）
kernel/edge_button/
├── edge_button.c
└── Makefile
dts/edge-gpio-overlay.dts             （加 edge-button 節點與 pin 33 的 pad 狀態）
apps/edge_button_wait.cpp             （C++：blocking read 印出 N 筆事件）
scripts/verify_edge_button.sh         （驗收：有 / 沒有 DT node；按一下、長按、快速連按要人按）
tests/test_edge_button_static.py
tests/test_edge_button_device.py
```

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
