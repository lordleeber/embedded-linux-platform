# 硬體接線與 pin mapping

狀態：按鍵在 Step 5-b 接線、Step 5-a 驗收後拆除（2026-10-10；Step 19 修 `ppoll()` 時要照下表原樣接回）；LED 在 Step 4-a 接線、Step 5-b 驗收前因材料不夠拆除（拆除前 Step 4-b 回歸測試 0 failure，人眼確認慢閃 5 下、最後熄滅），重跑 Step 4 驗收要先接回；其餘**尚未接線**。下表是每個預計使用的訊號的登錄欄位；`待確認` 不是接線指示。實際接線後，先從板卡及模組的原廠 pinout、schematic 核對實體 header 位置和電壓，再記錄 Linux controller / bus 名稱與實測結果。不要把 header pin 號當成 Linux GPIO 編號。

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
| LED signal（已拆除） | 29（GPIO01） | `gpiochip0`（tegra234-gpio）line 105 = PQ.05；pad `soc_gpio32_pq5`（pinmux 暫存器 `0x02430068`）；DT cell `TEGRA234_MAIN_GPIO(Q, 5)` = 125 | 3.3 V | 330 Ω → 紅色 LED 正極（長腳） | 已接線，active-high。Step 4-a 實測：JP6 開機 pad 為 tristate，LED 不亮；pad 開啟後 `edge_gpio_blink` 可閃爍（人眼確認） |
| LED GND | 30 | GND，非 bus | 0 V | 紅色 LED 負極（短腳） | 已拆除（Step 5-b） |
| Button signal（已拆除） | 33（GPIO13） | `gpiochip0` line 43 = PH.00；pad `soc_gpio21_ph0`；DT cell `TEGRA234_MAIN_GPIO(H, 0)` = 56；載板上經 TI TXB0108 電平轉換（規格書 SP-11324-001 Table 3-3 Note 3） | 3.3 V | 按鍵一腳；同一點經 330 Ω 上拉到 pin 1 | 已接線，active-low。只靠 SoC 內部上拉時恆讀 0（TXB0108 的 ~4 kΩ buffer 保持電位）；加 330 Ω 上拉後，Step 5-b / 5-a 的驗收都通過（按一下 pressed + released、長按、快速連按）。確認接線請用 `build/edge_gpio_button 4` 按兩下，**不要用單次 `gpioget`**：請求 line 後約 20 ms 內 pin 一律讀到 0（Step 5-a 實測），放開時也可能讀到 0；開機預設 pad 是 `pull=1`（下拉）`tristate=1 enable-input=1`，外接上拉蓋過下拉 |
| Button 上拉電源 | 1（3.3 V） | 電源，非 bus | 3.3 V | 330 Ω → pin 33 | 已拆除（Step 5-a 後） |
| Button GND | 34 | GND，非 bus | 0 V | 按鍵另一腳（四腳按鍵用對角兩腳） | 已拆除（Step 5-a 後） |
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
