# 硬體接線與 pin mapping

狀態：**尚未接線**（Step 1）。下表是每個預計使用的訊號的登錄欄位；`待確認` 不是接線指示。實際接線後，先從板卡及模組的原廠 pinout、schematic 核對實體 header 位置和電壓，再記錄 Linux controller / bus 名稱與實測結果。不要把 header pin 號當成 Linux GPIO 編號。

| 元件 / 訊號 | Jetson 40-pin header 實體 pin | Linux controller / bus | 電壓 | 對端 pin | 狀態 / 驗證 |
|---|---|---|---|---|---|
| INA219 VCC | 待確認 | 電源，非 bus | 待確認 | INA219 VCC | 未接線 |
| INA219 GND | 待確認 | GND，非 bus | 0 V | INA219 GND | 未接線 |
| INA219 SDA | 待確認 | I2C controller 待確認 | 待確認 | INA219 SDA | 未接線 |
| INA219 SCL | 待確認 | I2C controller 待確認 | 待確認 | INA219 SCL | 未接線 |
| OLED VCC | 待確認 | 電源，非 bus | 待確認 | OLED VCC | 未接線 |
| OLED GND | 待確認 | GND，非 bus | 0 V | OLED GND | 未接線 |
| OLED SDA | 待確認 | I2C controller 待確認 | 待確認 | OLED SDA | 未接線 |
| OLED SCL | 待確認 | I2C controller 待確認 | 待確認 | OLED SCL | 未接線 |
| LED signal | 待確認 | GPIO controller / line 待確認 | 待確認 | LED 限流電阻及正極 | 未接線 |
| STM32F103 GND | 待確認 | GND，非 bus | 0 V | STM32 GND | 未接線 |
| STM32F103 I2C SDA/SCL | 待確認 | I2C controller 待確認 | 待確認 | STM32 SDA/SCL 待確認 | 未接線 |
| STM32F103 SPI CLK/MOSI/MISO/CS | 待確認 | SPI controller 待確認 | 待確認 | STM32 SPI pins 待確認 | 未接線 |
| STM32F103 UART TX/RX | 待確認 | UART controller 待確認 | 待確認 | STM32 RX/TX 待確認 | 未接線 |
| STM32N657 訊號 | 待確認 | controller 待確認 | 待確認 | 對端 pin 待確認 | 未接線 |
| IMX219 camera | 不走 40-pin header | CSI connector 待確認 | 待確認 | camera ribbon connector 待確認 | 未接線 |

## 需要在接線時補充

1. 記錄每個模組的型號、供電規格與邏輯電平；確認 Jetson 介面和對端相容。
2. 記錄 header **實體 pin 號**、訊號名稱、Linux controller / `/dev/i2c-*` 或 `/dev/spidev*` 對應。若 Device Tree 變更，重查對應。
3. 記錄共地、限流電阻、I2C pull-up 與 INA219 分流電阻接法。電源路徑須另畫圖，避免把量測端誤接到資料腳。
4. 每完成一條線，記錄檢查方式與日期。通電前確認無短路，之後才在對應 Step 做 bus 掃描或功能測試。
