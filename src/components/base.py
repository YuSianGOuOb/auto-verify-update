from abc import ABC, abstractmethod
from src.core.logger import warn, info
from src.models.exceptions import TimeoutError
import time
import re
import json

class FirmwareComponent(ABC):
    def __init__(self, drivers, config):
        self.ssh = drivers.ssh
        self.redfish = drivers.redfish
        self.config = config
        self.name = config.name
        self.log_baseline = 0

    @abstractmethod
    def get_current_version(self, quiet=False) -> str:
        pass

    @abstractmethod
    def upload_firmware(self):
        pass

    @abstractmethod
    def monitor_update(self):
        pass

    # === 通用工具方法 ===

    def _extract_version(self, output):
        m = re.search(r'"([^"]+)"', output)
        return m.group(1) if m else "Unknown"

    def _clean_staging_area(self):
        try:
            info("Cleaning up BMC staging area (/tmp/images)...")
            self.ssh.send_command("rm -rf /tmp/images/*")
        except Exception as e:
            warn(f"Failed to clean staging area: {e}")

    def _record_log_baseline(self):
        try:
            cmd = "wc -l /var/log/redfish | awk '{print $1}'"
            output = self.ssh.send_command(cmd)
            self.log_baseline = int(output.strip())
            info(f"Log Baseline recorded: {self.log_baseline} lines")
        except Exception as e:
            warn(f"Failed to record log baseline: {e}")
            self.log_baseline = 0

    def _fetch_new_logs(self):
        try:
            count_cmd = "wc -l /var/log/redfish | awk '{print $1}'"
            curr_lines = int(self.ssh.send_command(count_cmd).strip())

            if self.log_baseline > 0 and curr_lines >= self.log_baseline:
                cmd = f"tail -n +{self.log_baseline + 1} /var/log/redfish"
            else:
                cmd = "tail -n 50 /var/log/redfish"

            return self.ssh.send_command(cmd)
        except Exception:
            return ""


    def reboot_bmc(self):
        """嘗試透過 Redfish (優先) 或 SSH 強制重啟 BMC"""
        info("Sending BMC Reboot command...")
        
        # 1. 嘗試 Redfish GracefulRestart
        try:
            endpoint = "/redfish/v1/Managers/bmc/Actions/Manager.Reset"
            payload = {"ResetType": "GracefulRestart"}
            self.redfish.post_action(endpoint, payload)
            info("Redfish restart command sent.")
            return
        except Exception as e:
            warn(f"Redfish reset failed: {e}. Trying SSH...")

        # 2. 失敗則嘗試 SSH reboot
        try:
            self.ssh.send_command("reboot")
            info("SSH reboot command sent.")
        except Exception:
            pass

    def wait_for_reboot(self, timeout=900):
        """
        等待 BMC 重啟完成：
        1. 斷開現有連線
        2. 迴圈嘗試 SSH 連線
        3. 檢查 D-Bus/Systemd 狀態
        """
        info("Waiting for BMC to come back online...")
        start_time = time.time()
        
        # 確保舊連線已關閉
        try:
            self.ssh.close()
        except:
            pass

        # 稍作延遲，避免機器還沒關機我們就連進去了
        time.sleep(15)

        while time.time() - start_time < timeout:
            try:
                # 嘗試建立新連線
                self.ssh.connect()
                info("[bold green]SSH Connection Restored![/bold green]")
                
                # 連線成功後，檢查服務是否 Ready
                self.wait_for_bmc_ready()
                return
            except Exception:
                # 連線失敗代表還在開機中，繼續等
                time.sleep(5)
        
        raise TimeoutError("BMC failed to come back online (SSH unreachable).")

    def wait_for_bmc_ready(self, quiet=False):
        """
        檢查 BMC 服務狀態。
        :param quiet: 若為 True，且 BMC 一次就檢查通過，則不印出任何 Log。
        """
        if not quiet:
            info("Checking BMC Readiness...")
        
        timeout = 600 
        start_time = time.time()
        logged_wait = False # 標記是否已經印過等待訊息
        
        # Stage 1: Check D-Bus State
        while time.time() - start_time < timeout:
            try:
                cmd = (
                    "busctl get-property xyz.openbmc_project.State.BMC "
                    "/xyz/openbmc_project/state/bmc0 "
                    "xyz.openbmc_project.State.BMC CurrentBMCState"
                )
                output = self.ssh.send_command(cmd)
                
                if "xyz.openbmc_project.State.BMC.BMCState.Ready" in output:
                    break
                
                # 如果檢查失敗（還沒 Ready），且 quiet=True，這時候才開始印 Log
                if quiet and not logged_wait:
                    info("BMC not ready yet, waiting...")
                    logged_wait = True
                
                time.sleep(5)
            except Exception:
                time.sleep(5)
        else:
            warn("Timeout waiting for D-Bus State 'Ready'. Proceeding...")

        # Stage 2: Check Systemd Jobs
        while time.time() - start_time < timeout:
            try:
                output = self.ssh.send_command("systemctl list-jobs")
                if "No jobs running" in output:
                    if not quiet:
                        info("[bold green]BMC is Fully Ready (No jobs running).[/bold green]")
                    elif logged_wait:
                        # 如果前面有印過等待訊息，這裡補一個完成訊息
                        info("[bold green]BMC is now Ready.[/bold green]")
                    return
                
                if quiet and not logged_wait:
                    info("Waiting for systemd jobs to finish...")
                    logged_wait = True
                    
                time.sleep(5)
            except Exception:
                time.sleep(5)

        warn("Timeout waiting for Systemd jobs. Proceeding anyway...")

    def verify_update(self):
        self.wait_for_bmc_ready()
        current = self.get_current_version(quiet=True)
        target = self.config.version
        
        if target.strip() not in current.strip():
             warn(f"[Verification Mismatch] Expected '{target}', but got '{current}'.")
        else:
             info(f"Version match verified: {current}")