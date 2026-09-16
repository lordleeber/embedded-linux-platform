# Phase 12 — STM32N657

> Parent roadmap: `ROADMAP.md`

STM32N657 留到最後。

不要只拿它做 GPIO / I2C。

它適合拿來做：

```text
MCU Edge AI
```

架構：

```text
Camera / Sensor
      ↓
STM32N657
      ↓
AI inference
      ↓
detection metadata
      ↓
SPI / UART
      ↓
Jetson C++ application
```

可以研究：

- Cortex-M55
- SIMD / Helium
- Neural-ART accelerator
- TinyML
- STM32Cube.AI
- DMA
- image preprocessing

最終形成：

```text
STM32N657
    ↓
低功耗 always-on AI
    ↓
發現事件
    ↓
喚醒 / 通知 Jetson
    ↓
Jetson 執行大型 YOLO
```

這已經是很完整的 heterogeneous embedded system。

---

# 最終 Project

可以把整體命名為：

```text
Embedded Platform
```

架構：

```text
                         ┌─────────────────┐
                         │     IMX219      │
                         └────────┬────────┘
                                  │ MIPI CSI
                                  ▼
┌────────────────────────────────────────────────┐
│              Jetson Orin Nano                  │
│                                                │
│ Yocto image                                    │
│ ├── meta-tegra                                 │
│ └── meta-edge                                  │
│                                                │
│ Linux Kernel                                   │
│ ├── edge_ina219 driver                         │
│ ├── edge_ctrl driver                           │
│ ├── GPIO / IRQ                                 │
│ ├── I2C / SPI                                  │
│ └── V4L2                                       │
│                                                │
│ Userspace                                      │
│ ├── platform-app                              │
│ ├── YOLO                                       │
│ ├── TensorRT                                   │
│ └── WebRTC / streaming                         │
└───────────────┬────────────────────────────────┘
                │
          I2C / SPI / GPIO
                │
                ▼
        ┌──────────────┐
        │ STM32F103    │
        │              │
        │ watchdog     │
        │ ADC          │
        │ GPIO         │
        │ sensor hub   │
        └──────────────┘

INA219 ───── I2C ───── Jetson
OLED   ───── I2C ───── Jetson
```

---

# 建議學習順序

嚴格按照：

```text
1. Character Device
        ↓
2. GPIO + IRQ
        ↓
3. INA219 + I2C
        ↓
4. hwmon
        ↓
5. OLED
        ↓
6. STM32F103 I2C Slave
        ↓
7. 自訂 Protocol
        ↓
8. Hardware Watchdog
        ↓
9. SPI + DMA
        ↓
10. poll / epoll
        ↓
11. C++ Userspace Hardware Integration
        ↓
12. Yocto / BitBake 基礎
        ↓
13. meta-tegra：build + flash Jetson image
        ↓
14. meta-edge：driver + Device Tree + application recipe
        ↓
15. Reproducible custom Linux image
        ↓
16. IMX219 / V4L2
        ↓
17. STM32N657 Edge AI
```

---

# 最重要的原則

每一階段都不要只做到：

```text
compile success
```

而要做到：

```text
Physical Hardware
        ↓
Kernel
        ↓
Userspace
        ↓
Application
        ↓
Yocto recipe / layer
        ↓
Reproducible image
```

整條路真的跑起來。

例如 INA219：

```text
battery
 ↓
INA219
 ↓
I2C
 ↓
你的 Linux driver
 ↓
hwmon
 ↓
platform-app
```

STM32：

```text
physical button
 ↓
STM32 firmware
 ↓
I2C/SPI
 ↓
你的 Linux driver
 ↓
poll()
 ↓
C++ application
```

Camera：

```text
photons
 ↓
IMX219
 ↓
MIPI CSI
 ↓
V4L2
 ↓
GStreamer
 ↓
C++ video pipeline
 ↓
YOLO
```

這樣學完後，你的能力就不再只是：

```text
C++ Application Engineer
```

而會往：

```text
Embedded Linux / Robotics System Software Engineer
```

延伸，而且每一項都能拿實際 project 和 code 證明。

<!-- STEP_PLAN_START -->
## Step 規劃

### Step 34-a — STM32N657 board + sensor input bring-up

**目標**

先建立可重複的 input path，不同時整合 AI model。

**規模目標**

```text
預估新增 code：300–600 lines
```

**實作範圍**

- board initialization
- camera/sensor input
- DMA buffer
- test frame / sample acquisition
- basic timing instrumentation


<!-- STEP_DETAIL_START -->
### 這一步到底要做什麼

STM32N657 先當一般 MCU 使用，先把 input path 做穩，不急著加 AI。

根據你實際 sensor/camera，建立：

```text
clock
GPIO
DMA
input peripheral
buffer
```

若是 camera，至少要能拿到一張 frame；若先用 synthetic input，也要能把固定 tensor/image 搬入同一 buffer path。

要記錄：

```text
buffer width/height
pixel format
stride
memory location
DMA completion
```

### 驗證

連續取得多個 input buffer，checksum/sequence 合理，不出現明顯 tearing/overwrite。

### 這一步不做

- 不跑 Neural-ART inference
<!-- STEP_DETAIL_END -->

**驗收條件**

MCU 可以穩定取得可重複驗證的 input buffer。

### Step 34-b — STM32Cube.AI / Neural-ART inference

**目標**

只完成 model deployment 與 inference。

**規模目標**

```text
預估新增 handwritten code：250–500 lines
```

**實作範圍**

- model conversion/config
- STM32Cube.AI integration
- Neural-ART runtime bring-up
- fixed input inference
- output verification


<!-- STEP_DETAIL_START -->
### 這一步到底要做什麼

把一個已知模型轉成 STM32Cube.AI / Neural-ART 能執行的形式，先用固定測試 input，不和真實 camera pipeline 混在一起。

流程：

```text
trained model
  ↓
conversion / compilation
  ↓
generated network/runtime assets
  ↓
MCU initialize
  ↓
fixed tensor input
  ↓
inference
  ↓
output tensor
```

要保存一份 PC reference output，MCU 結果必須在允許誤差內匹配。

### 驗證

至少記錄：

```text
init success
input shape/type
output shape/type
latency
peak/static memory usage
output comparison
```

### 這一步不做

- 不做 camera preprocessing
- 不做 Jetson transport
<!-- STEP_DETAIL_END -->

**驗收條件**

相同測試 input 可以得到可重複驗證的 inference result。

### Step 34-c — Preprocessing + benchmark + metadata

**目標**

把真實 input 接入 inference，並定義輸出 contract。

**規模目標**

```text
預估新增 code：300–550 lines
```

**實作範圍**

- resize / normalize / layout conversion
- end-to-end inference path
- latency / memory benchmark
- detection metadata format
- error/status metadata


<!-- STEP_DETAIL_START -->
### 這一步到底要做什麼

把 Step 34-a 的真實 input 接到 Step 34-b 的 model input。

明確實作：

```text
crop/resize
pixel format conversion
normalization
layout conversion (HWC/CHW)
quantization/dequantization（若需要）
```

輸出不要只是一堆 tensor value，要定義 metadata：

```text
sequence_id
timestamp
class_id
confidence
bbox
inference_time_us
status
```

### 驗證

同一張測試圖：

```text
PC preprocessing + model
vs
STM32 preprocessing + model
```

結果要可比較。

### 這一步不做

- 不送到 Jetson
<!-- STEP_DETAIL_END -->

**驗收條件**

STM32N657 可以輸出可驗證 detection metadata 與 latency。

### Step 35-a — Detection event transport to Jetson

**目標**

只建立 MCU → Jetson event/metadata transport。

**規模目標**

```text
預估新增 code：300–550 lines
```

**實作範圍**

- detection trigger
- SPI/UART metadata packet
- sequence / CRC
- Jetson receive path
- transport-level retry/error counters


<!-- STEP_DETAIL_START -->
### 這一步到底要做什麼

把 STM32N657 的 detection metadata 可靠送到 Jetson。這不是傳完整影像，而是傳小型事件。

packet 例如：

```text
MAGIC
VERSION
SEQ
TIMESTAMP
EVENT_TYPE
CLASS_ID
CONFIDENCE
BBOX
CRC
```

transport 可以選 SPI 或 UART，但一個 Step 只選一種主要路徑，不要兩個一起完成。

要定義：

```text
max packet size
timeout
CRC
sequence duplicate
retry
version mismatch
```

### 驗證

連續送至少 1000 個 synthetic detection event，Jetson 統計 loss/duplicate/CRC error。

### 這一步不做

- 不啟動 Jetson YOLO
<!-- STEP_DETAIL_END -->

**驗收條件**

Jetson 可以可靠收到 STM32N657 detection event 與 metadata。

### Step 35-b — Jetson AI action handler

**目標**

收到 event 後觸發 Jetson 端較大型 AI 工作，但不加入完整 power state machine。

**規模目標**

```text
預估新增 code：300–550 lines
```

**實作範圍**

- event handler
- input selection
- larger YOLO invocation
- result correlation
- timeout / failure handling


<!-- STEP_DETAIL_START -->
### 這一步到底要做什麼

Jetson 收到 detection event 後，決定是否執行較大的模型。

流程：

```text
STM32 event
  ↓
Jetson receiver
  ↓
validate packet
  ↓
select corresponding input/frame
  ↓
run larger YOLO
  ↓
correlate result with sequence_id
```

一定要有 timeout/error handling：

```text
event 到了但 frame 不存在
YOLO timeout/fail
duplicate event
event 太舊
```

### 驗證

用 synthetic event 也能觸發 end-to-end handler，不必每次靠真實 camera 才能測。

### 這一步不做

- 不做完整 low-power state machine
<!-- STEP_DETAIL_END -->

**驗收條件**

可以演示：

```text
STM32N657 detection
        ↓
Jetson notified
        ↓
Jetson runs larger YOLO
```

### Step 35-c — Always-on state machine + end-to-end logging

**目標**

最後才加入 heterogeneous system 的狀態管理。

**規模目標**

```text
預估新增 code：300–600 lines
```

**實作範圍**

- low-power / active states
- wake/event transitions
- cooldown / duplicate suppression
- end-to-end timestamps
- structured logging
- failure injection tests


<!-- STEP_DETAIL_START -->
### 這一步到底要做什麼

最後才把前面各模組串成可觀察的 heterogeneous system state machine。

建議 state：

```text
IDLE
  ↓ STM32 event
EVENT_RECEIVED
  ↓
JETSON_INFERENCE
  ↓
RESULT_READY
  ↓
COOLDOWN
  ↓
IDLE
```

也要有：

```text
ERROR
TIMEOUT
DUPLICATE_SUPPRESSED
```

每個 event 建議帶同一個 `sequence_id`，讓 log 可以從 MCU 一路追到 Jetson inference result。

### 要記錄的 timestamp

```text
MCU detection time
Jetson receive time
Jetson inference start
Jetson inference end
result complete
```

如此才能量 end-to-end latency，而不是只量 model inference。

### 驗證

做 fault injection：

```text
packet lost
duplicate event
Jetson inference failure
timeout
rapid repeated detections
```

確認系統最後能回到穩定 state。
<!-- STEP_DETAIL_END -->

**驗收條件**

可以完整追蹤：

```text
always-on detect
  ↓
event transport
  ↓
Jetson AI action
  ↓
result
  ↓
return to idle
```

<!-- STEP_PLAN_END -->
