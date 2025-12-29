from src.components.base import FirmwareComponent
from src.core.logger import info, error, info_block
from src.models.exceptions import UpdateFailedError, TimeoutError
import time
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

    def get_current_version(self, quiet=False):
        self.wait_for_bmc_ready(quiet=True)
        cmd = (
            "busctl get-property xyz.openbmc_project.Software.BMC.Updater "
            f"{self.meta['path']} xyz.openbmc_project.Software.Version Version"
        )
        output = self.ssh.send_command(cmd)
        ver = self._extract_version(output)
        if not quiet:
            info(f"CPLD {self.config.subtype} Version: {ver}")
        return ver

    def upload_firmware(self):
        self._clean_staging_area()
        self._record_log_baseline()
        self.host_power_off()

        # CPLD 特有的上傳參數
        info(f"Uploading CPLD {self.config.subtype}...")
        target = f"/redfish/v1/UpdateService/FirmwareInventory/{self.meta['target_uri']}"
        endpoint = "/redfish/v1/UpdateService/upload"
        
        result = self.redfish.post_file(
            endpoint=endpoint,
            file_path=self.config.file,
            payload={"Targets": [target]}
        )
        
        info("Upload Response:")
        info_block(json.dumps(result, indent=4), title="Upload Response")
        if "Id" in result:
             info(f"Task Created: ID = {result['Id']}")

    def monitor_update(self):
        info(f"Verifying CPLD {self.config.subtype} upload status...")
        timeout = 600
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            # [重構] 直接取得 Logs，不需要再手寫 awk/tail 指令
            logs = self._fetch_new_logs()
            
            # 檢查 CPLD 特有的成功/失敗關鍵字
            if "UpdateSuccessful" in logs:
                info(f"[bold green]CPLD {self.config.subtype} Upload successful.[/bold green]")
                self.check_system_logs()
                return

            if "ApplyFailed" in logs:
                error(f"Log content: {logs}")
                raise UpdateFailedError("CPLD Upload failed")
            
            time.sleep(5)
            
        raise TimeoutError("CPLD Upload verification timed out")