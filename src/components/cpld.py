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
        self.log_baseline = 0

    def get_current_version(self):
        cmd = (
            "busctl get-property xyz.openbmc_project.Software.BMC.Updater "
            f"{self.meta['path']} xyz.openbmc_project.Software.Version Version"
        )
        output = self.ssh.send_command(cmd)
        return self._extract_ver_from_busctl(output)

    def upload_firmware(self):
        # 1. 清理 BMC 暫存區
        try:
            info("Cleaning up BMC staging area (/tmp/images)...")
            self.ssh.send_command("rm -rf /tmp/images/*")
        except Exception as e:
            warn(f"Failed to clean staging area: {e}")

        # 2. 擷取 Log 基準線
        try:
            cmd = "wc -l /var/log/redfish | awk '{print $1}'"
            output = self.ssh.send_command(cmd)
            self.log_baseline = int(output.strip())
            info(f"Log Baseline recorded: {self.log_baseline} lines")
        except Exception as e:
            warn(f"Failed to record log baseline: {e}. Monitor might be inaccurate.")
            self.log_baseline = 0

        # 3. 執行上傳
        info(f"Uploading CPLD {self.config.subtype}...")
        
        target = f"/redfish/v1/UpdateService/FirmwareInventory/{self.meta['target_uri']}"
        endpoint = "/redfish/v1/UpdateService/upload"
        
        result = self.redfish.post_file(
            endpoint=endpoint,
            file_path=self.config.file,
            payload={"Targets": [target]}
        )
        
        info("Upload Response:")
        print(json.dumps(result, indent=4))
        
        if "Id" in result:
             info(f"Task Created: ID = {result['Id']}")

    def monitor_update(self):
        info(f"Verifying CPLD {self.config.subtype} upload status (scanning Redfish logs)...")
        timeout = 300
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                # 1. 取得當前行數
                count_cmd = "wc -l /var/log/redfish | awk '{print $1}'"
                curr_lines = int(self.ssh.send_command(count_cmd).strip())

                # 2. 智慧判斷
                if self.log_baseline > 0 and curr_lines >= self.log_baseline:
                    cmd = f"tail -n +{self.log_baseline + 1} /var/log/redfish"
                else:
                    cmd = "tail -n +1 /var/log/redfish"

                logs = self.ssh.send_command(cmd)
                
                # 3. 檢查
                if "UpdateSuccessful" in logs:
                    info(f"[bold green]CPLD {self.config.subtype} Upload verification successful (Staged).[/bold green]")
                    return

                if "ApplyFailed" in logs:
                    error(f"Log content: {logs}")
                    raise UpdateFailedError("CPLD Upload failed")
                    
            except Exception:
                pass

            time.sleep(5)
            
        raise TimeoutError("CPLD Upload verification timed out")

    def _extract_ver_from_busctl(self, output):
        m = re.search(r'"([^"]+)"', output)
        return m.group(1) if m else "Unknown"