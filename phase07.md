# Phase 7 — Jetson ↔ STM32 SPI

> Parent roadmap: `ROADMAP.md`

## 目的

I2C 熟悉後，開始處理更高速介面。

架構：

```text
Jetson SPI master
        │
        ▼
STM32 SPI slave
```

## 實作

自己設計 packet：

```text
HEADER
COMMAND
LENGTH
PAYLOAD
CRC
```

例如：

```text
0xAA
0x10
0x02
0x12 0x34
CRC
```

## 學習

- SPI
- full duplex
- DMA
- interrupt
- packet framing
- CRC
- synchronization

## Linux

先 userspace：

```text
spidev
```

再進一步：

```text
custom SPI kernel driver
```

---

<!-- STEP_PLAN_START -->
## Step 規劃

### Step 16 — SPI userspace loop / framing

**目標**

先用 `spidev` 驗證 Jetson ↔ STM32 SPI 實體鏈路。

**實作範圍**

- SPI master/slave bring-up
- HEADER / COMMAND / LENGTH / PAYLOAD / CRC
- loopback / known packet
- protocol parser


<!-- STEP_DETAIL_START -->
### 這一步到底要做什麼

從 I2C register protocol 轉向 packet-based SPI protocol。Jetson 為 SPI controller/master，STM32 為 SPI peripheral/slave。

先不要寫 kernel driver，先用 `/dev/spidevX.Y`。

定義 packet：

```text
MAGIC   1 byte
CMD     1 byte
LENGTH  2 bytes
SEQ     2 bytes
PAYLOAD N bytes
CRC     2 bytes
```

要明確定義：

- byte order
- maximum payload
- CRC algorithm
- invalid MAGIC 行為
- sequence number 是否回 echo
- request/response timing

### 驗證

先做固定 request：

```text
GET_DEVICE_INFO
```

STM32 回：

```text
DEVICE_ID
FW_VERSION
STATUS
```

連續 1000 次交易並統計：

```text
success
CRC error
timeout
unexpected response
```

### 這一步不做

- 不做 DMA
- 不寫 kernel SPI driver
<!-- STEP_DETAIL_END -->

**驗收條件**

可以穩定交換至少 1000 個 packet，並統計 CRC/error rate。

### Step 17-a — STM32 SPI DMA transport

**目標**

先完成 DMA-based SPI RX/TX transport，不同時實作完整 protocol recovery。

**規模目標**

```text
預估新增 code：300–550 lines
```

**實作範圍**

- DMA RX/TX
- transfer-complete interrupt
- ping-pong / ring buffer 基礎
- known-size packet exchange
- transport counters


<!-- STEP_DETAIL_START -->
### 這一步到底要做什麼

把 STM32 SPI receive/transmit 從 blocking/polling 改成 DMA transport。

先固定最大 packet buffer，例如：

```text
RX buffer 256 bytes
TX buffer 256 bytes
```

DMA 負責搬資料，CPU 只在：

```text
transfer complete
half complete（若需要）
error
```

時處理 callback。

要先把「transport」與「parser」分開：

```text
SPI DMA 收到 bytes
      ↓
transport buffer
      ↓
交給 parser
```

這一步 parser 可以很簡單，只接受已知長度 packet。

### 驗證

- 連續高頻 transaction
- CPU 不 busy-wait
- DMA error 有 counter
- buffer overwrite 不發生
- transfer 中不能重用尚未完成的 buffer
<!-- STEP_DETAIL_END -->

**驗收條件**

高頻連續傳輸時 MCU 不需要 busy-wait，且已知格式封包可穩定收發。

### Step 17-b — SPI parser + resynchronization

**目標**

在穩定 transport 上加入 protocol robustness。

**規模目標**

```text
預估新增 code：300–550 lines
```

**實作範圍**

- HEADER / LENGTH validation
- CRC validation
- malformed packet handling
- resynchronization
- parser error counters
- regression cases


<!-- STEP_DETAIL_START -->
### 這一步到底要做什麼

在 DMA transport 穩定後，才處理 packet framing 錯誤與重新同步。

parser 必須能面對：

```text
前面多一個 garbage byte
packet 被截斷
CRC 錯
LENGTH 不合理
MAGIC 錯
連續兩個 packet
```

不要假設每一次 SPI callback 一定剛好等於一個完整高層 packet。

建立 parser state，例如：

```text
WAIT_MAGIC
READ_HEADER
READ_PAYLOAD
READ_CRC
COMPLETE
```

### 驗證

建立 malformed packet test vectors。每一種錯誤之後，都要能重新找到下一個合法 packet，而不是只能 reset MCU 才恢復。
<!-- STEP_DETAIL_END -->

**驗收條件**

注入 truncated / bad CRC / garbage bytes 後，可以恢復到下一個合法封包。

### Step 18-a — Minimal Linux SPI driver

**目標**

先只建立 Linux SPI subsystem 的最小 driver。

**規模目標**

```text
預估新增 code：250–450 lines
```

**實作範圍**

- `spi_driver`
- probe/remove
- basic transfer
- DT match
- transport-level counters


<!-- STEP_DETAIL_START -->
### 這一步到底要做什麼

把 Step 16 的 `/dev/spidevX.Y` 實驗移到 Linux SPI subsystem driver。

Device Tree 要描述 SPI chip-select、frequency、mode 等資訊。

driver 內：

```text
spi_driver
  ↓
probe(struct spi_device *)
  ↓
spi_sync()/spi_async()
```

先實作一個最小「讀 device info」transaction，不急著 expose 複雜 userspace API。

### 驗證

- probe 由 DT match 正確觸發
- SPI mode/clock 正確
- kernel path 可以取得 STM32 device info
- timeout/error 有明確 errno

### 這一步不做

- 不做完整 character device
- 不做 `poll()`
<!-- STEP_DETAIL_END -->

**驗收條件**

kernel driver 可以和 STM32 完成一個已知 request/response。

### Step 18-b — SPI userspace bridge + protocol reuse

**目標**

再把前面的 protocol 暴露給 userspace。

**規模目標**

```text
預估新增 code：300–550 lines
```

**實作範圍**

- character-device or sysfs bridge
- shared packet definition
- error propagation
- userspace test client
- protocol regression test


<!-- STEP_DETAIL_START -->
### 這一步到底要做什麼

把 Linux SPI driver 的 packet transaction 暴露給 userspace，讓 application 不需要知道 `spidev`。

可以建立：

```text
/dev/edge_ctrl
```

定義最小 userspace contract：

```text
read status
send command
get device info
```

共享 protocol 結構要放在明確 header，而不是 kernel/user 各自複製一份不同版本。

### 驗證

userspace client 完全不打開 `/dev/spidevX.Y`，仍能完成 Step 16 相同功能。

### 這一步不做

- 不做 asynchronous event wait
- 留給 Step 19
<!-- STEP_DETAIL_END -->

**驗收條件**

userspace 不再直接操作 `/dev/spidevX.Y` 也能與 STM32 通訊。

<!-- STEP_PLAN_END -->
