# 驗收基線與踩坑紀錄

## Step 1：可重複的開發環境

- 驗收主機：Jetson Orin Nano Engineering Reference Developer Kit Super，Ubuntu 22.04.5 LTS，JetPack 套件 `6.2.1+b38`，L4T R36 revision 4.7，kernel `5.15.148-tegra`，aarch64。完整原始輸出見 [jetson-version.txt](jetson-version.txt)。
- 對照方法：在同一台 Jetson 執行 `bash scripts/check_host_env.sh`；逐項核對 board model、L4T release、kernel headers 和 8 個必需指令皆為 `PASS`。版本字串不設數值容差；kernel release / headers 路徑應一致。升級後先更新快照，再評估後續 module 相容性。
- 自動測試：`python3 -m unittest discover -s tests -v`，4 個案例通過，涵蓋全部可用、缺少 `dtc`、缺少 `v4l2-ctl` 時仍產生版本快照，以及缺少板型 / L4T 資料。
- 教材檢查：`python3 scripts/check_book.py docs`。
- 硬體：尚未接線；接線驗收與 bus 通訊均未實測。

### 踩坑

- 原本以為有 `/lib/modules/$(uname -r)/build` 連結就能代表 headers 完全可用；腳本目前只驗證目錄可達，真正的 module build 須留待 Step 2 驗證。
- 原本以為 L4T release 可以直接代表已安裝的 JetPack 套件版本；這台機器兩者分開記錄，避免日後只看到 L4T 便推定 JetPack 版本。
