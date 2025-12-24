from src.components.base import FirmwareComponent
from src.core.logger import info, error, warn
from src.models.exceptions import UpdateFailedError, TimeoutError
import time
import json

class BIOSComponent(FirmwareComponent):
    DBUS_PATH = "/xyz/openbmc_project/software/BIOS"

    def get_current_version(self, quiet=False):
        self.wait_for_bmc_ready(quiet=True)
        cmd = (
            "busctl get-property xyz.openbmc_project.Software.BMC.Updater "
            f"{self.DBUS_PATH} xyz.openbmc_project.Software.Version Version"
        )
        output = self.ssh.send_command(cmd)
        ver = self._extract_version(output)
        if not quiet:
            info(f"BIOS Version: {ver}")
        return ver

    def upload_firmware(self):
        self._clean_staging_area()
        self._record_log_baseline()

        info("Uploading BIOS firmware with OEM parameters...")
        endpoint = "/redfish/v1/UpdateService/upload"
        
        payload = {
            "UpdateParameters": {
                "Oem": {"QCT_IO": {"Preserve": True}}
            }
        }
        
        result = self.redfish.post_file(
            endpoint=endpoint,
            file_path=self.config.file,
            payload=payload 
        )
        
        info("Upload Response:")
        print(json.dumps(result, indent=4))
        if "Id" in result:
             info(f"Task Created: ID = {result['Id']}")

    def monitor_update(self):
        info("Verifying BIOS upload status...")
        timeout = 600
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            logs = self._fetch_new_logs()
                
            if "UpdateSuccessful" in logs or "AwaitToActivate" in logs:
                info("[bold green]BIOS Upload verification successful (Staged/Await).[/bold green]")
                return

            if "ApplyFailed" in logs:
                error(f"Log content: {logs}")
                raise UpdateFailedError("BIOS Upload failed")

            time.sleep(5)
            
        raise TimeoutError("BIOS Upload verification timed out")