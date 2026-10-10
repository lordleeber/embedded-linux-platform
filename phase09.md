# Phase 9 — C++ Userspace Hardware Integration

> Parent roadmap: `ROADMAP.md`

## 目的

前面的 Phase 已經分別完成：

```text
INA219 → hwmon
STM32 → Linux driver
GPIO / IRQ
poll / epoll
```

這一階段不是整合回任何既有專案，而是在 **本 repo 內建立一個獨立的 C++ userspace application**，用來驗證前面做好的 Linux hardware interfaces。

暫定名稱：

```text
platform-app
```

它只是本 repo 的 userspace 範例 / 驗證程式，不依賴其他 repo。

整體資料流：

```text
INA219
  ↓
Linux hwmon
  ┐
  │
STM32
  ↓
edge_ctrl driver
  │
  ├──────────────┐
  │              │
  ▼              ▼
BatteryMonitor  ControlDevice
       \        /
        \      /
        platform-app
```

這一階段的重點是不要讓 application 到處直接操作：

```text
/sys/class/hwmon/...
/dev/edge_ctrl
ioctl()
poll()
```

而是建立清楚的 C++ abstraction。

---

## Step 規劃

### Step 21 — C++ hardware abstraction

**目標**

建立本 repo 自己的 C++ hardware abstraction layer，將 Linux-specific I/O 細節集中起來。

**實作範圍**

- `BatteryMonitor`
- `ControlDevice`
- `HardwareEventLoop`
- error/status model
- mockable interface
- 最小 `platform-app`
- 順帶整理（Step 5-a code review 延後）：`edge_gpio_button.cpp` 與 `edge_button_wait.cpp` 的參數解析、signal 設定、印事件迴圈幾乎相同，收進 abstraction；`scripts/verify_edge_*.sh` 裡重複的 `pinconf`、`pin_level`、`check_events`、`held_seconds` 抽成共用的 shell 檔

### 這一步到底要做什麼

把前面 Linux 細節藏到 C++ abstraction 後面，避免 application 到處散落：

```text
open()
ioctl()
read()
poll()
sysfs path
```

建議 interface：

```cpp
class BatteryMonitor {
public:
    BatterySample read();
};

class ControlDevice {
public:
    DeviceStatus get_status();
    std::vector<HardwareEvent> read_events();
};
```

實作層才知道：

```text
/sys/class/hwmon/...
/dev/edge_ctrl
ioctl()
poll()
```

`platform-app` 只依賴 C++ interface：

```text
platform-app
   ↓
BatteryMonitor / ControlDevice
   ↓
Linux-specific implementation
   ↓
hwmon / character device
```

同時提供 fake/mock implementation，讓 application logic 可以在沒有 Jetson hardware 的一般 Linux PC 上測。

### 預期檔案

```text
apps/platform-app/
├── main.cpp
├── CMakeLists.txt
└── README.md

include/platform/
├── battery_monitor.hpp
├── control_device.hpp
└── hardware_event.hpp

src/platform/
├── battery_monitor_linux.cpp
└── control_device_linux.cpp

tests/
└── platform/
```

### 驗證

`platform-app` 至少可以輸出：

```text
battery voltage/current/power
STM32 device status
STM32 firmware version
received hardware event
```

application main code 不應直接包含：

```text
/dev/edge_ctrl
/sys/class/hwmon
ioctl command number
```

### 這一步不做

- 不做 battery low policy
- 不做 retry/backoff policy
- 不做 Yocto packaging
- 不整合任何外部 repo

**驗收條件**

本 repo 內的 `platform-app` 可以透過明確 C++ interface 讀 battery、STM32 status 與 hardware events。

---

### Step 22 — Application-level hardware policies

**目標**

在 `platform-app` 中把硬體 telemetry 轉成可測試的 application state，而不是把 policy 塞回 kernel driver。

**實作範圍**

- battery state
- hardware health state
- event logging
- retry/backoff
- degraded mode
- clean shutdown

### 這一步到底要做什麼

定義至少三種 scenario：

```text
battery low
STM32 offline
driver read error
```

例如 battery state：

```text
Battery >= 20%  → NORMAL
Battery < 20%   → LOW
Battery < 10%   → CRITICAL
```

threshold 必須放 config 或集中定義，不要散落 hardcode。

STM32 offline 也要定義：

```text
一次 read fail ≠ offline
連續 N 次 fail → DEGRADED
持續超過 timeout → OFFLINE
```

建議 application state：

```text
NORMAL
LOW_BATTERY
DEGRADED
HARDWARE_OFFLINE
```

資料流：

```text
Linux driver / hwmon
        ↓
C++ abstraction
        ↓
normalized hardware state
        ↓
platform-app policy
```

### 測試方式

使用 Step 21 的 fake/mock implementation 注入：

```text
11.9 V
9.5 V
I/O error
STM32 timeout
recovery
```

不需要真的拔線才能跑 regression test。

### 這一步不做

- 不做 Yocto packaging
- 不依賴任何外部 application repo

**驗收條件**

可以注入：

```text
battery low
STM32 offline
driver read error
hardware recovery
```

並得到可預期且可自動測試的 application state transition。
