# Phase 8 — poll / epoll / blocking I/O

> Parent roadmap: `ROADMAP.md`

## 目的

把 driver 和你原本熟悉的 Linux networking knowledge 接起來。

讓：

```text
/dev/edge_ctrl
```

支援：

```c
poll()
```

userspace：

```cpp
poll(...)
```

或：

```cpp
epoll(...)
```

等待 STM32 event。

架構：

```text
STM32 Button
    ↓
GPIO / IRQ
    ↓
Linux driver
    ↓
wait_queue
    ↓
poll()
    ↓
C++ application
```

這一階段會把：

```text
kernel event
```

和：

```text
Linux asynchronous I/O
```

真正串起來。

---

<!-- STEP_PLAN_START -->
## Step 規劃

### Step 19 — poll() support

**目標**

讓 `/dev/edge_ctrl` 具備真正的 event-driven API。

**實作範圍**

- wait queue
- driver `.poll`
- event flag / event queue
- C++ `poll()` client
- timeout/error handling
- 順帶修正（Step 5-a code review 延後）：`apps/edge_button_wait.cpp`、`apps/edge_gpio_button.cpp` 在「檢查 signal 旗標」和「進入 `read()`」之間有競態，signal 剛好落在中間時要等到下一個事件才醒；改用 `ppoll()` 搭配 signal mask 根治（驗收腳本目前靠 `timeout -k` 兜底）


<!-- STEP_DETAIL_START -->
### 這一步到底要做什麼

讓 `/dev/edge_ctrl` 可以被 `poll()` 等待。

現在 userspace 不應：

```text
while (true) {
    read_status();
    sleep(10ms);
}
```

而要：

```text
poll(fd)
  ↓ sleep
STM32 event / GPIO IRQ
  ↓
driver 設 event pending
  ↓
wake_up_interruptible()
  ↓
poll() returns readable
```

driver 要實作：

```c
.poll = edge_ctrl_poll
```

並使用 wait queue。

### 要定義 event semantics

至少明確回答：

- 一次 event 是一個 bit 還是一個 queue entry？
- 同類事件連續發生兩次會不會 lost？
- userspace read 後何時清除 pending？
- buffer full 怎麼辦？

### 驗證

沒有事件時 CPU usage 應接近 idle；事件發生時 latency 可量測。
<!-- STEP_DETAIL_END -->

**驗收條件**

沒有 event 時 userspace 不 busy-loop；STM32 event 發生後 `poll()` 立即返回。

### Step 20 — epoll multi-source event loop

**目標**

把 device fd 與 Linux networking fd 放進同一套 event loop。

**實作範圍**

- `epoll_create1`
- device fd
- timerfd 或 socket fd
- clean shutdown
- event dispatch abstraction


<!-- STEP_DETAIL_START -->
### 這一步到底要做什麼

把 device fd 跟 networking fd 放進同一個 Linux event loop。

建立最小 C++ event loop：

```text
epoll fd
 ├── /dev/edge_ctrl
 ├── timerfd
 └── TCP/UDP socket
```

不要用 thread-per-fd 來避開問題。

要處理：

```text
EPOLLIN
EPOLLERR
EPOLLHUP
shutdown signal
```

可以加入 `eventfd` 或 self-pipe 做 clean shutdown。

### 驗證

同一 process 同時：

```text
等待 STM32 event
接收 socket packet
收到 periodic timer
```

且其中一個 fd 出錯不會讓整個 loop spin。
<!-- STEP_DETAIL_END -->

**驗收條件**

單一 C++ event loop 可以同時等待：

```text
STM32 event
network socket
timer
```
<!-- STEP_PLAN_END -->
