# Step 1：Jetson bring-up

這份紀錄對應 `phase00.md` 的 Step 1。Jetson 是受檢的 target；檢查腳本從系統讀取資料，無 bus controller / target 交易，也不改動硬體設定。

## 重跑環境檢查

在 Jetson 上執行：

```bash
bash scripts/check_host_env.sh
bash scripts/check_host_env.sh --record docs/jetson-version.txt
```

腳本逐項輸出 `PASS` / `FAIL`。全部通過回傳 0；任一必需工具或平台資料缺失回傳 1；參數或快照檔寫入錯誤回傳 2。`--record` 會覆寫指定檔案，請只在要更新基線時使用。快照仍會在工具檢查失敗時寫出，方便排查。

檢查項目包括 `gcc`、`g++`、`cmake`、`make`、`git`、`dtc`（`device-tree-compiler`）、`i2cdetect`（`i2c-tools`）及 `v4l2-ctl`（`v4l-utils`）。板型取自 `/proc/device-tree/model`；L4T 取自 `/etc/nv_tegra_release`；JetPack 套件版本從 `dpkg-query` 讀取（未安裝時標 `unavailable`）；kernel headers 檢查 `/lib/modules/$(uname -r)/build` 目錄。快照另記 `Kernel headers present: yes/no`，即使檢查失敗仍可看出當時目錄是否存在。此檢查只確認目錄存在，並不保證 headers 可以成功編譯或與執行中的 kernel ABI 完全相符。Step 2 已實際用這份 headers 編出 `edge_test.ko` 並成功載入（見 [baseline.md](baseline.md) 的 Step 2 段落）。

## 目前基線

已在 Jetson Orin Nano Engineering Reference Developer Kit Super 實機執行，結果見 [jetson-version.txt](jetson-version.txt) 與 [baseline.md](baseline.md)。要搬到另一台機器或升級系統時，先重跑環境檢查並比對 kernel release、L4T、JetPack、板型，然後再進行 module / Device Tree 工作。

## 接線驗收

目前沒有接線。接上任何元件前，先填 [hardware-wiring.md](hardware-wiring.md) 的 40-pin header 與對端 pin，查證電壓、共地、controller 與 Linux bus 名稱。只在完成核對後，把狀態改成「已接線、已驗證」。Step 1 不進行 I2C 掃描、GPIO 切換或 firmware 下載。

## 自動驗收

```bash
python3 -m unittest discover -s tests -v
python3 scripts/check_book.py docs
```

第一個指令以假的 Jetson 系統檔和工具路徑，驗證正常、缺工具、缺板型 / L4T、缺 headers 及產生快照的情境；第二個檢查教材連結與章節導覽。
