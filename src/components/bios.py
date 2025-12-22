from src.components.base import FirmwareComponent
from src.core.logger import info, error, warn
from src.models.exceptions import UpdateFailedError, TimeoutError
import time
import re
import json  # [新增] 用於序列化 OEM Payload

class BIOSComponent(FirmwareComponent):
    # 參考 modules/bios/device_map.py
    DBUS_PATH = "/xyz/openbmc_project/software/BIOS"

    def get_current_version(self):
        cmd = (
            "busctl get-property xyz.openbmc_project.Software.BMC.Updater "
            f"{self.DBUS_PATH} xyz.openbmc_project.Software.Version Version"
        )
        output = self.ssh.send_command(cmd)
        return self._extract_ver_from_busctl(output)

    def upload_firmware(self):
        """
        參考 modules/bios/upload.py，並加入 OEM Payload
        """
        # 1. 紀錄 Log 基準線
        try:
            cmd = "wc -l /var/log/redfish | awk '{print $1}'"
            output = self.ssh.send_command(cmd)
            self.log_baseline = int(output.strip())
            info(f"Log Baseline recorded: {self.log_baseline} lines")
        except Exception as e:
            warn(f"Failed to record log baseline: {e}")
            self.log_baseline = 0

        # 2. 準備 Payload
        info("Uploading BIOS firmware with OEM parameters...")
        endpoint = "/redfish/v1/UpdateService/upload"
        
        # [FIX] 建構 OEM Payload
        # QCT 機器通常要求將複雜物件轉為 JSON 字串傳送
        oem_payload = {
            "QCT_IO": {
                "Preserve": True
            }
        }

        payload = {
            "Oem": json.dumps(oem_payload)
        }
        
        # 3. 執行上傳
        self.redfish.post_file(
            endpoint=endpoint,
            file_path=self.config.file,
            payload=payload 
        )

    def monitor_update(self):
        info("Monitoring BIOS update (scanning NEW Redfish logs)...")
        
        # BIOS 更新通常較久，設定 600秒 (10分鐘)
        timeout = 600
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                # 讀取新增的 Log
                if getattr(self, 'log_baseline', 0) > 0:
                    cmd = f"tail -n +{self.log_baseline + 1} /var/log/redfish"
                else:
                    cmd = "tail -n 20 /var/log/redfish"

                logs = self.ssh.send_command(cmd)
                
                # 檢查成功關鍵字
                if "Update.1.0.UpdateSuccessful" in logs:
                    if self.config.version in logs:
                        info(f"[bold green]Update successful! Found version {self.config.version} in logs.[/bold green]")
                    else:
                        info("[bold green]Update successful event found (Version check skipped in logs).[/bold green]")
                    return

                # 檢查失敗關鍵字
                if "ApplyFailed" in logs:
                    error(f"Log content: {logs}")
                    raise UpdateFailedError("BIOS Update failed (ApplyFailed found in logs)")
                    
            except Exception as e:
                pass

            time.sleep(10) # BIOS 更新不用太頻繁輪詢
            
        raise TimeoutError("BIOS Update timed out")

    def _extract_ver_from_busctl(self, output):
        m = re.search(r'"([^"]+)"', output)
        return m.group(1) if m else "Unknown"