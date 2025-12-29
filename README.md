# Auto Verify Update Tool

這是一個專為 OpenBMC 伺服器設計的自動化韌體更新與驗證工具。透過整合 **Redfish API** 與 **SSH/D-Bus** 指令，實現了從韌體上傳、更新監控、自動重開機到最終版號與系統日誌（SEL）健康檢查的全自動化流程。

## 🚀 主要功能

* **彈性測試目標**：支援定義完整的升級路徑（Upgrade Path），亦可針對單一設備（如僅 BMC 或 CPLD）進行獨立的更新驗證測試。
* **多元件支援**：支援 BMC、BIOS 與 CPLD 的韌體更新。
* **完整驗證流程**：
    * **Pre-check**: 更新前確認當前版本。
    * **Monitor**: 監控更新過程中的 Redfish Task 或 Log 狀態。
    * **Post-check**: 重啟後驗證版號是否正確。
* **系統檢查**：
    * 自動比對更新前後的 **IPMI SEL (System Event Log)**。
    * 驗證 `UpdateSuccessful` 等關鍵日誌。
* **PFR 支援**：針對 PFR (Platform Firmware Resiliency) 系統提供額外的健康狀態檢查邏輯（開發中）。

## 🛠️ 安裝與環境準備

本工具已容器化，執行環境僅需安裝 **Docker**。

### 1. 取得專案程式碼
```bash
git clone <repository_url>
cd auto-verify-update
```

### 2. 賦予執行權限 首次使用前，請確認 run 腳本具有執行權限：
```bash
chmod +x run
```

### 3. 準備韌體檔案 :
請將您的韌體檔案 (.tar, .bin, .hpm) 放入專案目錄下的 img/ 資料夾中（或依照設定檔路徑配置）。

## ⚙️ 設定說明 (config/inventory.yaml)

請在 config/inventory.yaml 中定義連線資訊與更新目標。

```YAML
system:
  profile: "Server_Rack_A"
  type: "Standard"        # 支援 "Standard" 或 "PFR"
  connection:
    ip: "192.168.1.100"
    user: "admin"
    pass: "password"
    root_pass: "root_password" # 用於 SSH 取得更高權限

updates:
  # (請參考下方「標準驗證流程」配置)
```

## 📝 標準驗證流程範例 (Standard Validation Workflow)

在 `inventory.yaml` 中，`updates:` 列表下的定義順序即為程式的執行順序。這使得您可以設計複雜的升級/降級路徑（Downgrade/Upgrade Path）來驗證系統的穩定性。

以下是建議的標準驗證流程設定 (config/inventory.yaml)：
```YAML
# ... (system settings omitted) ...

updates:
  # Step 1: 降版測試 (Downgrade to Old Version)
  - name: "BMC_Downgrade_Old"
    type: "BMC"
    version: "3.24.00"               # 舊版本號
    file: "/app/img/bmc_old.tar"
    apply_time: "Immediate"
    preserve: true

  # Step 2: 升版測試 (Upgrade Old -> New)
  - name: "BMC_Upgrade_New"
    type: "BMC"
    version: "3.25.00"               # 新版本號
    file: "/app/img/bmc_new.tar"
    apply_time: "Immediate"
    preserve: true

  # Step 3: 重刷測試 (Re-flash New -> New)
  - name: "BMC_Reflash_New"
    type: "BMC"
    version: "3.25.00"
    file: "/app/img/bmc_new.tar"
    apply_time: "Immediate"
    preserve: true

  # Step 4: CPLD 更新
  - name: "MB_CPLD"
    type: "CPLD"
    version: "1.0.0"
    file: "/app/img/cpld.hpm"

  # Step 5: BIOS 更新
  - name: "System_BIOS"
    type: "BIOS"
    version: "1.2.0"
    file: "/app/img/bios.bin"

  # Step 6: 恢復出廠設定測試 (Factory Reset)
  - name: "BMC_Factory_Reset"
    type: "BMC"
    version: "3.25.00"
    file: "/app/img/bmc_new.tar"
    apply_time: "OnReset"            # 使用 OnReset 確保完整重置
    preserve: false                  # false = 清除所有設定 (需手動介入)
```

### ⚠️ 後續手動操作 (Post-Validation Steps)

由於流程最後一步執行了 Non-Preserve ，BMC 的 IP 可能變動且密碼將被重置，請依序執行以下步驟完成驗證：

  * **斷電重啟** (AC Cycle)：請對機台進行斷電並重新上電。

  * **重設密碼**：

      * **等待 BMC 啟動完成**。

      * **前往 BMC 網頁介面 (Web UI)**。

      * **使用預設帳號密碼登入，並依照提示修改為標準密碼**。

  * **最終版本確認**： 執行以下指令，確認所有元件版本皆正確無誤：
  ```Bash
  ./run -v
  ```

## 💻 執行方式

本專案提供 `./run` 腳本，會自動建置 Docker 映像檔並啟動容器執行。

### 1. 初次執行 (First Run)
您可以直接執行`./run`，腳本會自動檢查並建置 Docker 環境。 若日後修改了程式碼或想強制重建環境，才需要執行：

```bash
./run --build
```

### 2. 完整更新流程 (Update + Verify)
環境建置完成後，使用預設設定檔 `config/inventory.yaml` 進行標準更新流程：

```bash
./run
```

### 3. 僅驗證模式 (Verification Only)

不執行更新，僅透過 SSH/D-Bus 檢查當前版號是否符合設定檔中的 version，並以表格顯示結果：

```bash
./run -v
```

適合用於快速檢查機台目前的韌體狀態，或在 AC Cycle 後進行最終確認。

### 4. 單一設備/元件獨立測試 (Single Component Test)
若您只想測試特定元件（例如只驗證 CPLD 更新）或有多個機台設定，不需要修改原本的 `inventory.yaml`。
建議建立一個專屬的設定檔（例如 `config/cpld_only.yaml`），並在 `updates` 列表中僅保留該元件再透過 `-c` 指定：
```bash
./run -c config/cpld_only.yaml
```

```yaml
# config/cpld_only.yaml
system:
  # ... (連線資訊同上)
updates:
  - name: "CPLD_Test_Only"
    type: "CPLD"
    version: "1.0.0"
    file: "./img/CPLD/cpld.hpm"
```

## 📂 專案結構
```Plaintext
.
├── config/                 # 設定檔目錄
│   └── inventory.yaml
├── img/                    # (建議) 放置韌體檔案的目錄
├── src/
│   ├── components/         # 各元件實作 (BMC, BIOS, CPLD)
│   ├── core/               # 核心引擎與 Logger
│   ├── drivers/            # 底層驅動 (SSH, Redfish)
│   ├── machines/           # 系統驗證邏輯 (Standard, PFR)
│   └── models/             # 資料模型與 Exceptions
├── main.py                 # 程式進入點
├── Dockerfile              # Docker 建置檔
└── requirements.txt        # Python 依賴清單
```

## 📝 注意事項

  * **SSH 權限**：工具依賴 SSH 執行 busctl 與 ipmitool 指令，請確保帳號具有相應權限。

  * **韌體路徑**：設定檔中的 file 路徑是相對於程式執行位置（或 Docker 內的 /app 路徑），請確保路徑正確。

  * **Preserve 設定**：若 preserve: false，更新後 BMC IP 或密碼可能會重置，工具會提示需手動介入確認。

## 📜 License

MIT License