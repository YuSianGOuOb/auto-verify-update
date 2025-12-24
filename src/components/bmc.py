from src.components.base import FirmwareComponent
from src.core.logger import info, error, warn
from src.models.exceptions import TimeoutError
import time
import paramiko

class BMCComponent(FirmwareComponent):
    SERVICE = "xyz.openbmc_project.Software.BMC.Updater"
    PRIMARY_PATH = "/xyz/openbmc_project/software/BMCPrimary"
    SECONDARY_PATH = "/xyz/openbmc_project/software/BMCSecondary"

    def get_current_version(self, quiet=False):
        self.wait_for_bmc_ready(quiet=True)
        # 1. 判斷 Boot Source
        try:
            boot_source = self.ssh.send_command("/usr/bin/processBootInfo -i").strip()
        except Exception:
            boot_source = "Primary"

        # 2. 取得雙邊版本
        pri_ver = self._get_ver_from_dbus(self.PRIMARY_PATH)
        sec_ver = self._get_ver_from_dbus(self.SECONDARY_PATH)

        # [新增] quiet 控制
        if not quiet:
            info(f"BMC Versions - Primary: [cyan]{pri_ver}[/cyan], Secondary: [dim]{sec_ver}[/dim]")
            info(f"Active Boot Source: [bold yellow]{boot_source}[/bold yellow]")

        # 3. 根據 Boot Source 決定回傳哪個版本
        if "Alternate" in boot_source:
            if not quiet: info("Verifying against [magenta]Secondary[/magenta] version.")
            return sec_ver
        else:
            if not quiet: info("Verifying against [magenta]Primary[/magenta] version.")
            return pri_ver

    def _get_ver_from_dbus(self, object_path):
        try:
            cmd = (
                f"busctl get-property {self.SERVICE} "
                f"{object_path} xyz.openbmc_project.Software.Version Version"
            )
            output = self.ssh.send_command(cmd)
            return self._extract_version(output)
        except Exception:
            return "Unknown"

    def upload_firmware(self):
        self._clean_staging_area()
        self._record_log_baseline()

        info(f"Uploading BMC firmware: {self.config.file}")
        endpoint = "/redfish/v1/UpdateService/upload"
        
        payload = {
            "UpdateParameters": {
                "@Redfish.OperationApplyTime": "Immediate",
                "Oem": {"QCT_IO": {"Preserve": True}}
            }
        }

        result = self.redfish.post_file(
            endpoint=endpoint,
            file_path=self.config.file,
            payload=payload 
        )
        
        info("Upload Response:")
        import json
        print(json.dumps(result, indent=4))
        
        if "Id" in result:
             info(f"Task Created: ID = {result['Id']}")

    def monitor_update(self):
        info("Monitoring BMC update (Auto Reboot Expected)...")
        
        timeout = 600
        start_time = time.time()
        
        # 迴圈檢查直到：1. 更新成功 或 2. 斷線 (重開機開始)
        while time.time() - start_time < timeout:
            try:
                # Heartbeat
                self.ssh.send_command("echo check", timeout=5)

                # 檢查 Log
                logs = self._fetch_new_logs()

                if "UpdateSuccessful" in logs:
                    info("[bold green]Update Success confirmed! Initiating reboot sequence...[/bold green]")
                    # 有時候 BMC 雖然寫成功但還沒重開，我們這裡強制推一把，確保流程繼續
                    time.sleep(10) 
                    self.reboot_bmc()
                    self.wait_for_reboot()
                    return

            except (paramiko.ssh_exception.SSHException, OSError, ConnectionResetError):
                info("[bold yellow]Connection lost (Reboot detected). Waiting for recovery...[/bold yellow]")
                # 斷線了，直接進入等待恢復流程
                self.wait_for_reboot()
                return
            
            except Exception as e:
                # 處理 Socket closed 等非標準 Exception
                if "closed" in str(e) or "not connected" in str(e):
                    info("[bold yellow]Connection lost. Waiting for recovery...[/bold yellow]")
                    self.wait_for_reboot()
                    return
                warn(f"Monitor warning: {e}")
                time.sleep(5)
            
            time.sleep(5)

        warn("Timeout waiting for reboot event.")