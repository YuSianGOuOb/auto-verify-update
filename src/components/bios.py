from src.components.base import FirmwareComponent
from src.core.logger import info, error, warn
from src.models.exceptions import UpdateFailedError, TimeoutError
import time
import re
import json
import paramiko # 確保 paramiko 有被引入

class BIOSComponent(FirmwareComponent):
    DBUS_PATH = "/xyz/openbmc_project/software/BIOS"

    def get_current_version(self):
        cmd = (
            "busctl get-property xyz.openbmc_project.Software.BMC.Updater "
            f"{self.DBUS_PATH} xyz.openbmc_project.Software.Version Version"
        )
        output = self.ssh.send_command(cmd)
        return self._extract_ver_from_busctl(output)

    def upload_firmware(self):
        # 1. 清理暫存區
        try:
            info("Cleaning up BMC staging area (/tmp/images)...")
            self.ssh.send_command("rm -rf /tmp/images/*")
        except Exception as e:
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

        # 3. 準備 Payload (OEM)
        info("Uploading BIOS firmware with OEM parameters...")
        endpoint = "/redfish/v1/UpdateService/upload"
        
        parameters_json_content = {
            "Oem": {
                "QCT_IO": {
                    "Preserve": True
                }
            }
        }
        payload = {
            "UpdateParameters": parameters_json_content
        }
        
        # 4. 執行上傳
        result = self.redfish.post_file(
            endpoint=endpoint,
            file_path=self.config.file,
            payload=payload 
        )
        
        info("Upload Response:")
        print(json.dumps(result, indent=4))
        
        if "Id" in result:
             info(f"Task Created: ID = {result['Id']}")

    def reboot_bmc(self):
        info("Sending Redfish Force Restart command...")
        try:
            endpoint = "/redfish/v1/Managers/bmc/Actions/Manager.Reset"
            payload = {"ResetType": "GracefulRestart"}
            self.redfish.post_action(endpoint, payload)
        except Exception as e:
            warn(f"Failed to send Redfish reset: {e}")
            try:
                self.ssh.send_command("reboot")
            except:
                pass

    def monitor_update(self):
        info("Verifying BIOS upload status (scanning Redfish logs)...")
        timeout = 300
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                # 1. 取得當前行數
                count_cmd = "wc -l /var/log/redfish | awk '{print $1}'"
                curr_lines = int(self.ssh.send_command(count_cmd).strip())

                # 2. 智慧判斷讀取範圍
                if self.log_baseline > 0 and curr_lines >= self.log_baseline:
                    # 只讀新增的
                    cmd = f"tail -n +{self.log_baseline + 1} /var/log/redfish"
                else:
                    # 發生輪替，讀全部
                    cmd = "tail -n +1 /var/log/redfish"

                logs = self.ssh.send_command(cmd)
                
                # 3. 檢查
                if "UpdateSuccessful" in logs or "AwaitToActivate" in logs:
                    info("[bold green]BIOS Upload verification successful (Staged/Await).[/bold green]")
                    return

                if "ApplyFailed" in logs:
                    error(f"Log content: {logs}")
                    raise UpdateFailedError("BIOS Upload failed")
                    
            except Exception:
                pass

            time.sleep(5)
            
        raise TimeoutError("BIOS Upload verification timed out")
    
    def _extract_ver_from_busctl(self, output):
        m = re.search(r'"([^"]+)"', output)
        return m.group(1) if m else "Unknown"