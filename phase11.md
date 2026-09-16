# Phase 11 — IMX219 / V4L2

> Parent roadmap: `ROADMAP.md`

前面的 Linux driver 概念熟悉後，再開始碰 camera。

第一階段不要直接要求出影像。

## Step 1

了解：

```text
IMX219
   │
  I2C
   │
sensor configuration
```

自己讀：

```text
chip ID
```

做到：

```text
edge-imx219: sensor detected
edge-imx219: chip id = ...
```

## Step 2

加入：

```text
power
reset
clock
regulator
```

## Step 3

學：

```text
V4L2 subdevice
media controller
device tree endpoint
```

## Step 4

理解：

```text
IMX219
  ↓
MIPI CSI-2
  ↓
NVCSI
  ↓
VI
  ↓
V4L2
  ↓
/dev/videoX
```

## Step 5

最終接回：

```text
IMX219
    ↓
Linux camera driver
    ↓
V4L2
    ↓
GStreamer
    ↓
video_source_node
    ↓
YOLO
```

這會是整條 roadmap 中最難的一關。

---

<!-- STEP_PLAN_START -->
## Step 規劃

### Step 31 — IMX219 sensor identification

**目標**

先只處理 sensor control plane，不要求出影像。

**實作範圍**

- I2C communication
- chip ID
- power/reset/clock/regulator 盤點
- Device Tree endpoint 研究


<!-- STEP_DETAIL_START -->
### 這一步到底要做什麼

IMX219 bring-up 第一個目標不是畫面，而是證明 sensor control plane 正確。

要確認：

```text
I2C address
chip ID register
power rail
reset GPIO
external clock
regulator
```

建立最小 sensor probe：

```text
power on
  ↓
release reset
  ↓
enable clock
  ↓
I2C read chip ID
  ↓
power off/error cleanup
```

### 驗證

`dmesg` 要能清楚看到：

```text
sensor detected
chip id = expected value
```

拔掉 camera 或 address 錯誤時必須明確失敗，不得仍顯示「成功」。

### 這一步不做

- 不建立 `/dev/videoX`
- 不要求 streaming
<!-- STEP_DETAIL_END -->

**驗收條件**

kernel log 明確顯示 IMX219 被偵測，並可讀到合理 chip ID。

### Step 32-a — Minimal V4L2 subdevice registration

**目標**

先讓 sensor 成為合法的 V4L2 subdevice，不一次完成所有 format/control 邏輯。

**規模目標**

```text
預估新增 code：350–600 lines
```

**實作範圍**

- `v4l2_subdev`
- entity / pad
- probe/remove
- basic power state
- minimal media registration
- `media-ctl` visibility


<!-- STEP_DETAIL_START -->
### 這一步到底要做什麼

把 IMX219 從「會回 chip ID 的 I2C device」註冊成 Linux Media/V4L2 framework 看得懂的 sensor subdevice。

需要建立：

```text
v4l2_subdev
media_entity
source pad
subdev ops
```

此時可以只支援一個固定 mode，不要一開始塞所有 resolution/frame rate。

資料結構要清楚分：

```text
sensor private state
current format
power state
I2C client
subdev object
```

### 驗證

```bash
media-ctl -p
```

可以看到 IMX219 entity/pad。

### 這一步不做

- 不要求 capture node
- 不做完整 mode table
<!-- STEP_DETAIL_END -->

**驗收條件**

IMX219 subdevice 可以被 media controller 正確列出。

### Step 32-b — Format negotiation + media endpoint

**目標**

再加入 format 與 endpoint negotiation。

**規模目標**

```text
預估新增 code：300–550 lines
```

**實作範圍**

- source pad format
- supported resolution/mode table
- get/set format
- media bus code
- Device Tree endpoint integration
- `v4l2-ctl` / `media-ctl` regression


<!-- STEP_DETAIL_START -->
### 這一步到底要做什麼

讓上游 capture pipeline 可以跟 IMX219 協商「你要輸出什麼格式」。

至少明確定義：

```text
media bus code
width
height
field
colorspace（若相關）
frame mode
```

先支援 1–2 個實際使用 mode，比一次加入十幾種 mode 更容易驗證。

Device Tree endpoint 需要描述 sensor 與 CSI receiver 的連線，例如：

```text
remote-endpoint
data-lanes
clock-lanes（依平台需要）
```

### 驗證

用：

```text
media-ctl
v4l2-ctl
```

查詢/設定 format，確認兩端 media graph 沒有 format mismatch。

### 這一步不做

- 不接 GStreamer
<!-- STEP_DETAIL_END -->

**驗收條件**

media graph 正確，而且 sensor format 可以被 userspace 查詢與設定。

### Step 33-a — MIPI CSI → /dev/videoX capture path

**目標**

先完成 kernel/media capture path，不同時處理 GStreamer application pipeline。

**規模目標**

```text
預估新增 code/config：300–600 lines
```

**實作範圍**

- CSI / NVCSI / VI integration
- Device Tree linkage
- `/dev/videoX`
- raw frame capture
- capture error inspection


<!-- STEP_DETAIL_START -->
### 這一步到底要做什麼

把 sensor subdevice 真正連到 Jetson 的 CSI/NVCSI/VI capture path，最後出現可讀取的 capture device。

資料路徑：

```text
IMX219 pixel array
  ↓
MIPI CSI-2
  ↓
NVCSI
  ↓
VI
  ↓
V4L2 capture node
  ↓
/dev/videoX
```

這一步要先用最底層 V4L2 tool 抓 frame，不急著用 GStreamer。

### 驗證

例如：

```bash
v4l2-ctl --stream-mmap --stream-count=100 ...
```

確認：

- 能抓 100+ frames
- frame size 正確
- 沒有持續 CSI timeout/error
- stop/start streaming 可以重複執行

### 這一步不做

- 不做 encode
- 不做 YOLO
<!-- STEP_DETAIL_END -->

**驗收條件**

可以用 V4L2 tool 穩定取得 frame：

```text
IMX219 → CSI-2 → NVCSI → VI → V4L2
```

### Step 33-b — V4L2 → GStreamer pipeline + stability test

**目標**

在已經穩定的 `/dev/videoX` 上建立 userspace pipeline。

**規模目標**

```text
預估新增 code/scripts：200–450 lines
```

**實作範圍**

- GStreamer source pipeline
- format conversion
- frame-rate measurement
- dropped/error counters
- sustained-run test


<!-- STEP_DETAIL_START -->
### 這一步到底要做什麼

在 `/dev/videoX` 已經穩定後，再建立 GStreamer pipeline。如此出問題時才能知道是 V4L2 還是 GStreamer。

先做最簡：

```text
V4L2 source
  ↓
format conversion（若需要）
  ↓
fakesink/display/file
```

再量：

```text
actual fps
dropped frames
pipeline errors
CPU usage
```

建立 sustained test，例如 10–30 分鐘。

### 驗證

不只「有一張圖」，而是：

```text
持續 streaming
fps 接近設定
沒有 memory 持續增加
stop/start 可重複
```

### 這一步不做

- 不整合 YOLO
<!-- STEP_DETAIL_END -->

**驗收條件**

可以穩定擷取影像，並清楚畫出：

```text
IMX219 → CSI-2 → NVCSI → VI → V4L2 → GStreamer
```

<!-- STEP_PLAN_END -->
