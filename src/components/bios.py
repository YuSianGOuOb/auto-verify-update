from src.components.base import FirmwareComponent
from src.core.logger import info, error, info_block, warn
from src.models.exceptions import UpdateFailedError, TimeoutError
import time
import json

class BIOSComponent(FirmwareComponent):
    DEFAULT_PATH = "/xyz/openbmc_project/software/BIOS"

    def get_current_version(self, quiet=False):
        self.wait_for_bmc_ready(quiet=True)
        
        # [使用解構後的參數]
        target_path = self.primary_path or self.DEFAULT_PATH
        
        cmd = (
            "busctl get-property xyz.openbmc_project.Software.BMC.Updater "
            f"{target_path} xyz.openbmc_project.Software.Version Version"
        )
        output = self.ssh.send_command(cmd)
        ver = self._extract_version(output)
        if not quiet:
            info(f"BIOS Version: {ver}")
        return ver

    def upload_firmware(self):
        self.host_power_off()
        self._clean_staging_area()
        self._record_log_baseline()

        info("Uploading BIOS firmware...")
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
        info(f"Verifying BIOS upload status (Timeout: {self.timeout}s)...")
        start_time = time.time()
        
        while time.time() - start_time < self.timeout:
            logs = self._fetch_new_logs()
            if "UpdateSuccessful" in logs or "AwaitToActivate" in logs:
                info("[bold green]BIOS Upload verification successful.[/bold green]")
                self.check_system_logs()
                self.host_power_on()
                self.wait_for_host_boot()
                return

            if "ApplyFailed" in logs:
                raise UpdateFailedError("BIOS Upload failed")

            time.sleep(5)
            
        raise TimeoutError("BIOS Upload verification timed out")