from src.components.base import FirmwareComponent
from src.core.logger import info, error, info_block
from src.models.exceptions import UpdateFailedError, TimeoutError
import time
import json

class CPLDComponent(FirmwareComponent):
    # [修正] 移除了 __init__ 與 MAPPING，完全依賴 strategies.yaml 的設定
    
    def get_current_version(self, quiet=False):
        self.wait_for_bmc_ready(quiet=True)
        
        # [使用解構後的參數]
        # 注意：Base.py 裡將 verify_path 映射到了 primary_path
        target_path = self.primary_path
        
        if not target_path:
            return "Unknown (No verify_path configured)"

        cmd = (
            "busctl get-property xyz.openbmc_project.Software.BMC.Updater "
            f"{target_path} xyz.openbmc_project.Software.Version Version"
        )
        output = self.ssh.send_command(cmd)
        ver = self._extract_version(output)
        if not quiet:
            # [修改] 改用 self.name (例如 "MB_CPLD")
            info(f"{self.name} Version: {ver}")
        return ver

    def upload_firmware(self):
        self._clean_staging_area()
        self._record_log_baseline()
        self.host_power_off()

        info(f"Uploading {self.name}...")
        endpoint = self.update_endpoint
        
        # [使用解構後的參數]
        result = self.redfish.post_file(
            endpoint=endpoint,
            file_path=self.config.file,
            payload=self.payload
        )
        
        info_block(json.dumps(result, indent=4), title="Upload Response")
        if "Id" in result:
             info(f"Task Created: ID = {result['Id']}")

    def monitor_update(self):
        info(f"Verifying CPLD upload status (Timeout: {self.timeout}s)...")
        start_time = time.time()
        
        while time.time() - start_time < self.timeout:
            logs = self._fetch_new_logs()
            if "UpdateSuccessful" in logs:
                info(f"[bold green]CPLD Upload successful.[/bold green]")
                self.check_system_logs()
                return
            if "ApplyFailed" in logs:
                raise UpdateFailedError("CPLD Upload failed")
            time.sleep(5)
            
        raise TimeoutError("CPLD Upload verification timed out")