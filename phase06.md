# Phase 6 — Hardware Watchdog

> Parent roadmap: `ROADMAP.md`

## 目的

讓 STM32 不只是 peripheral，而成為 Jetson 的 supervisor。

架構：

```text
Jetson
   │
heartbeat
   │
   ▼
STM32F103
```

Jetson 每：

```text
500 ms
```

送一次 heartbeat。

STM32：

```text
超過 3 秒沒收到
        ↓
判斷 Jetson 異常
        ↓
LED / GPIO / Reset
```

## 學習重點

STM32：

- independent watchdog
- timer
- state machine

Linux：

- kernel timer
- delayed work
- watchdog subsystem

後面甚至可以研究：

```text
/dev/watchdog
```

---

<!-- STEP_PLAN_START -->
## Step 規劃

### Step 14 — STM32 heartbeat supervisor

**目標**

讓 STM32 能判斷 Jetson 是否失去 heartbeat。

**實作範圍**

- STM32 timer
- heartbeat timeout
- state machine
- fault LED / GPIO
- timeout test


<!-- STEP_DETAIL_START -->
### 這一步到底要做什麼

讓 STM32 從「被動 peripheral」升級成「Jetson supervisor」。

Jetson 週期性寫一個 heartbeat register，例如：

```text
0x32 HEARTBEAT
```

不要把 value 本身當重點，可以每次寫遞增 sequence：

```text
1, 2, 3, 4 ...
```

STM32 每收到有效 heartbeat：

```text
last_heartbeat_time = now
```

若：

```text
now - last_heartbeat_time > 3 seconds
```

就進入 fault state。

STM32 state machine 建議：

```text
BOOT
  ↓
WAIT_FOR_HEARTBEAT
  ↓
HEALTHY
  ↓ timeout
FAULT
```

### 驗證

- 正常 heartbeat 10 分鐘不誤報
- 停止 Jetson sender 後約 3 秒進 FAULT
- heartbeat 恢復後，是否自動恢復要明確定義
- sequence 卡住時是否算有效 heartbeat，也要定義

### 從 Step 12-a 帶過來的

- STM32 端 I2C1 卡住的完整復原（PR #21 code review）：12-a 在 BERR / ARLO / OVR 之後只做 SWRST + 重新設定，不是 ES096 對「analog filter 讓 BUSY 卡住」的完整解法（PE = 0、SCL / SDA 切成 GPIO open-drain、手動切換電位確認讀回、切回 AF、SWRST）。這一步做 supervisor 時，順便決定 firmware 要怎麼偵測「BUSY 卡住、0x42 不再回應」（例如 BUSY 持續一段時間且沒有事件），再補完整解法。現在沒有重現方法，要先找到重現方式或照實標「未實測」

### 從 Step 12-b 帶過來的

- `write_reg()` 的最後一個分支把「有定義、可寫、不是 LED_CONTROL」的位址都當成 STATUS 做 write-1-to-clear（PR #23 code review）。現在可寫的只有這兩個，所以沒錯；這一步加 HEARTBEAT（可寫）時，要先替它加自己的分支或在 `REGS[]` 加 setter，並寫一個「寫 HEARTBEAT 不會清 STATUS」的向量（先紅再實作）

### 這一步不做

- 不直接 reset Jetson
- 先用 LED/GPIO 表示 fault
<!-- STEP_DETAIL_END -->

**驗收條件**

停止 heartbeat 超過門檻後，STM32 進入 fault state。

### Step 15 — Linux watchdog integration

**目標**

把 heartbeat 與 Linux watchdog 概念接起來。

**實作範圍**

- delayed work / kernel timer
- periodic heartbeat
- watchdog subsystem 研究或最小整合
- `/dev/watchdog` 行為測試
- recovery / failure 文件


<!-- STEP_DETAIL_START -->
### 這一步到底要做什麼

把 Step 14 的 heartbeat sender 從臨時 userspace script 整合到 Linux side，並理解 Linux watchdog subsystem。

先做一個明確的週期工作：

```text
kernel delayed_work 或 userspace service
  ↓ every 500 ms
write heartbeat register
```

然後研究 Linux `/dev/watchdog` 的標準語意：

```text
open
keepalive
timeout
close/magic close
```

這一步的重點是比較：

```text
Linux software watchdog
vs
STM32 external hardware supervisor
```

外部 STM32 的價值在於 Jetson kernel/system 本身卡死時，它仍可能偵測不到 heartbeat。

### 驗證

做 fault injection：

```text
停止 service
kill process
讓 sender thread 卡住
暫停 I2C
```

逐一確認 STM32 fault behavior。

### 這一步不做

- 不直接加入 power-cut circuit
- 不做實際硬 reset，除非另開後續硬體 safety step
<!-- STEP_DETAIL_END -->

**驗收條件**

可以清楚演示：

```text
normal heartbeat
fault injection
timeout
STM32 detects failure
```
<!-- STEP_PLAN_END -->
