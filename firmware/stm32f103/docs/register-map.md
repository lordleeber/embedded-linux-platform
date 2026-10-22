# STM32F103 I2C target — register map (Step 11)

Controller（master）是 Jetson，target（slave）是 Blue Pill 的 I2C1（PB6 = SCL、PB7 = SDA），
7-bit 位址 **0x42**。每個 register 都是 1 byte。

| 位址 | 名稱 | 存取 | 值 / reset 預設 | 說明 |
|---|---|---|---|---|
| 0x00 | DEVICE_ID | RO | 0xED | 固定值，用來確認接上的是這份 firmware |
| 0x01 | FW_MAJOR | RO | 0x00 | firmware 版本 major |
| 0x02 | FW_MINOR | RO | 0x01 | firmware 版本 minor（Step 11 = 0.1） |
| 0x20 | LED_CONTROL | RW | 0x00 | 0 = 板載 LED（PC13）滅，1 = 亮 |

## Transaction

```text
寫：START 0x42+W  reg  data  STOP
讀：START 0x42+W  reg  RESTART  0x42+R  byte  STOP     （i2cget 的 byte data 讀法）
```

- 寫入的第 1 個 byte 是 register pointer，第 2 個 byte 是資料，之後的 byte 都丟掉。
- 讀取時每個 byte 都是同一個 register（Step 11 **不做 auto-increment**；多 byte 讀取在 Step 12-a 才定義）。
- 每次寫入都會改 pointer；之後的讀取如果沒先寫 pointer，就讀上次選的那個 register。

## 不合法的存取

| 情況 | bus 上 | 結果 |
|---|---|---|
| 寫 RO register（0x00–0x02） | ACK | 丟掉，值不變 |
| 寫沒定義的 register | ACK | 丟掉 |
| LED_CONTROL 寫 0、1 以外的值 | ACK | 丟掉，LED 保持原狀 |
| 讀沒定義的 register | ACK | 回 0xFF |

F103 的 I2C 在 firmware 看到 byte 之前就已經由硬體回 ACK，所以 target 沒辦法用 NACK 拒絕一個值。
Jetson 要確認寫入有沒有生效，就把 register 讀回來看。Step 12-a 會加 STATUS register 回報錯誤。
