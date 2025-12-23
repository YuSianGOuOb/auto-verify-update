from src.components.base import FirmwareComponent
from src.core.logger import info, error, warn
from src.models.exceptions import UpdateFailedError, TimeoutError
import time
import re
import json

class CPLDComponent(FirmwareComponent):
    MAPPING = {
        "MB":  {"path": "/xyz/openbmc_project/software/MBCPLD", "target_uri": "CPLD_MB"},
        "FAN": {"path": "/xyz/openbmc_project/software/FANCPLD", "target_uri": "CPLD_FAN"},
        "SSD": {"path": "/xyz/openbmc_project/software/SSDCPLD", "target_uri": "CPLD_SSD"},
        "SCM": {"path": "/xyz/openbmc_project/software/SCMCPLD", "target_uri": "CPLD_SCM"}
    }

    def __init__(self, drivers, config):
        super().__init__(drivers, config)
        if config.subtype not in self.MAPPING:
            raise ValueError(f"Unknown CPLD subtype: {config.subtype}")
        self.meta = self.MAPPING[config.subtype]
        # 初始化 Log 基準線
        self.log_baseline = 0

    def get_current_version(self):
        cmd = (
            "busctl get-property xyz.openbmc_project.Software.BMC.Updater "
            f"{self.meta['path']} xyz.openbmc_project.Software.Version Version"
        )
        output = self.ssh.send_command(cmd)
        return self._extract_ver_from_busctl(output)

    def upload_firmware(self):
        # [NEW] 1. 清理 BMC 暫存區 (防止空間不足或舊檔干擾)
        try:
            info("Cleaning up BMC staging area (/tmp/images)...")
            # rm -rf 不會報錯即使目錄為空，非常安全
            # 注意：OpenBMC 的上傳路徑通常是 /tmp/images，如果不確定，清 /tmp 裡的特定檔案也可
            self.ssh.send_command("rm -rf /tmp/images/*")
        except Exception as e:
            # 清理失敗不應該阻擋流程，印個警告就好
            warn(f"Failed to clean staging area: {e}")

        # 2. 紀錄 Log 基準線
        try:
            cmd = "wc -l /var/log/redfish | awk '{print $1}'"
            output = self.ssh.send_command(cmd)
            self.log_baseline = int(output.strip())
            info(f"Log Baseline recorded: {self.log_baseline} lines")
        except Exception as e:
            warn(f"Failed to record log baseline: {e}")
            self.log_baseline = 0
        """
        在上傳前先記錄 Log 行數，確保 monitor 不會抓到舊資料
        """
        # [NEW] 1. 擷取 Log 基準線 (Baseline)
        try:
            # 使用 wc -l 計算行數，並用 awk 取第一欄數字
            cmd = "wc -l /var/log/redfish | awk '{print $1}'"
            output = self.ssh.send_command(cmd)
            self.log_baseline = int(output.strip())
            info(f"Log Baseline recorded: {self.log_baseline} lines")
        except Exception as e:
            warn(f"Failed to record log baseline: {e}. Monitor might be inaccurate.")
            self.log_baseline = 0

        # [EXISTING] 2. 執行上傳
        info(f"Uploading CPLD {self.config.subtype}...")
        
        target = f"/redfish/v1/UpdateService/FirmwareInventory/{self.meta['target_uri']}"
        endpoint = "/redfish/v1/UpdateService/upload"
        
                # 接住回傳值 (Response JSON)
        result = self.redfish.post_file(
            endpoint=endpoint,
            file_path=self.config.file,
            payload={"Targets": [target]}
        )
        
        # 印出結果
        info("Upload Response:")
        print(json.dumps(result, indent=4)) # 漂亮列印 JSON
        
        # 如果回傳中有 Task ID，也可以特別印出來
        if "Id" in result:
             info(f"Task Created: ID = {result['Id']}")

    def monitor_update(self):
        """
        [FIX] 使用基準線來監控新增的 Log
        """
        info("Monitoring CPLD update (scanning NEW Redfish logs)...")
        
        timeout = 600
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                # 組合指令：從 (基準線 + 1) 行開始讀取到最後
                # tail -n +K 代表從第 K 行開始讀
                if self.log_baseline > 0:
                    cmd = f"tail -n +{self.log_baseline + 1} /var/log/redfish"
                else:
                    # 如果基準線獲取失敗，只好退回讀最後 20 行 (有風險)
                    cmd = "tail -n 20 /var/log/redfish"

                logs = self.ssh.send_command(cmd)
                
                # 檢查關鍵字
                if "Update.1.0.UpdateSuccessful" in logs:
                    info("[bold green]Update successful event found in NEW logs![/bold green]")
                    return

                if "ApplyFailed" in logs:
                    error(f"Log content: {logs}")
                    raise UpdateFailedError("CPLD Update failed (ApplyFailed found in logs)")
                    
            except Exception as e:
                # 連線或指令錯誤時忽略，繼續重試
                pass

            time.sleep(5)
            
        raise TimeoutError("CPLD Update timed out (success log not found)")

    def _extract_ver_from_busctl(self, output):
        m = re.search(r'"([^"]+)"', output)
        return m.group(1) if m else "Unknown"