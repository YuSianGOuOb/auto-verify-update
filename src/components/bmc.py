from src.components.base import FirmwareComponent
from src.core.logger import info, error, warn
from src.models.exceptions import UpdateFailedError, TimeoutError
import time
import re
import json
import paramiko  # [新增] 用於捕捉 SSHException

class BMCComponent(FirmwareComponent):
    # [FIX] 根據您的 busctl 指令更新路徑
    SERVICE = "xyz.openbmc_project.Software.BMC.Updater"
    PRIMARY_PATH = "/xyz/openbmc_project/software/BMCPrimary"
    SECONDARY_PATH = "/xyz/openbmc_project/software/BMCSecondary"

    def get_current_version(self):
        """
        取得目前的 BMC 版本。
        會同時抓取 Primary 和 Secondary 顯示在 Log，但以 Primary 為準。
        """
        # 1. 抓取 Primary (主要驗證對象)
        pri_ver = self._get_ver_from_dbus(self.PRIMARY_PATH)
        
        # 2. 抓取 Secondary (參考用)
        sec_ver = self._get_ver_from_dbus(self.SECONDARY_PATH)

        info(f"BMC Versions Check - Primary: [cyan]{pri_ver}[/cyan], Secondary: [dim]{sec_ver}[/dim]")
        
        # 回傳 Primary 版本供系統驗證
        return pri_ver

    def _get_ver_from_dbus(self, object_path):
        try:
            # 使用 get-property 比 grep 更精準
            cmd = (
                f"busctl get-property {self.SERVICE} "
                f"{object_path} xyz.openbmc_project.Software.Version Version"
            )
            output = self.ssh.send_command(cmd)
            return self._extract_ver_from_busctl(output)
        except Exception:
            return "Unknown"

    def upload_firmware(self):
        # 1. 清理暫存區
        try:
            info("Cleaning up BMC staging area...")
            self.ssh.send_command("rm -rf /tmp/images/*")
        except Exception:
            pass

        # 2. 準備上傳
        info(f"Uploading BMC firmware: {self.config.file}")
        endpoint = "/redfish/v1/UpdateService/upload"
        
        # 3. 設定參數 (Immediate + Preserve)
        update_params_content = {
            "@Redfish.OperationApplyTime": "Immediate",
            "Oem": {
                "QCT_IO": {
                    "Preserve": True
                }
            }
        }

        payload = {
            "UpdateParameters": update_params_content
        }

        # 4. 執行上傳
        # 接住回傳值 (Response JSON)
        result = self.redfish.post_file(
            endpoint=endpoint,
            file_path=self.config.file,
            payload=payload 
        )
        
        # 印出結果
        info("Upload Response:")
        print(json.dumps(result, indent=4)) # 漂亮列印 JSON
        
        # 如果回傳中有 Task ID，也可以特別印出來
        if "Id" in result:
             info(f"Task Created: ID = {result['Id']}")

    def monitor_update(self):
        info("Monitoring BMC update (Hybrid: Log Scan + Auto/Manual Reboot)...")
        
        timeout = 600
        start_time = time.time()
        reboot_started = False
        update_success_found = False
        
        # --- 階段 1: 監控 Log 直到斷線 (維持原本邏輯) ---
        while time.time() - start_time < timeout:
            try:
                # 嘗試檢查 SSH 是否還活著
                try:
                    self.ssh.send_command("echo check", timeout=5)
                except Exception:
                    info("[bold yellow]SSH Connection lost. Reboot initiated![/bold yellow]")
                    reboot_started = True
                    break

                # 讀取 Log 邏輯 (省略，維持您原本的程式碼)
                if getattr(self, 'log_baseline', 0) > 0:
                    cmd = f"tail -n +{self.log_baseline + 1} /var/log/redfish"
                else:
                    cmd = "tail -n 20 /var/log/redfish"
                
                logs = self.ssh.send_command(cmd, timeout=10)

                if "ApplyFailed" in logs:
                    raise UpdateFailedError("BMC Update failed (ApplyFailed found in logs)")
                
                if "Update.1.0.UpdateSuccessful" in logs and not update_success_found:
                    info("[bold green]Update successful event found in logs![/bold green]")
                    update_success_found = True
                    info("Waiting 30s for automatic reboot...")
                    time.sleep(30)
                    
                    try:
                        self.ssh.send_command("echo check", timeout=5)
                        info("[bold yellow]BMC did not reboot automatically. Forcing reboot...[/bold yellow]")
                        self.reboot_bmc()
                    except Exception:
                        pass # 斷線了，進入重連階段

            except Exception as e:
                if not reboot_started:
                    info(f"[bold yellow]Connection dropped ({e}). Reboot started![/bold yellow]")
                    reboot_started = True
                    break
            
            time.sleep(5)

        # --- 階段 2: 強固的重連機制 (重點修改) ---
        if not reboot_started:
            warn("Timeout reached without detecting reboot. BMC might be stuck.")

        info("Waiting for BMC to come back online...")
        reconnect_timeout = 600
        start_reconnect = time.time()
        
        while time.time() - start_reconnect < reconnect_timeout:
            try:
                # 1. 先確保舊連線關閉
                try:
                    self.ssh.close()
                except:
                    pass
                
                # 2. 稍微緩衝，不要瘋狂 retry 導致 BMC 鎖住
                time.sleep(5) 
                
                # 3. 嘗試連線
                # 這裡最容易發生 Connection Reset，因為 Port 22 通了但服務沒好
                self.ssh.connect()
                
                # 4. 如果連線成功，測試一下指令確保真的能用
                self.ssh.send_command("echo online", timeout=5)
                
                info("[bold green]BMC is back online and SSH re-established![/bold green]")
                time.sleep(10) # 讓服務完全跑完
                return

            except (paramiko.ssh_exception.SSHException, OSError, ConnectionResetError) as e:
                # [關鍵修正] 捕捉 Connection reset by peer 或 Banner error
                # 這些都是 "BMC 還在開機" 的特徵，不是程式錯誤
                # 我們把錯誤轉為 Info Log，繼續等待
                print(f"[Wait] BMC booting up... ({str(e)})")
                time.sleep(5)

            except Exception as e:
                # 其他未預期的錯誤
                warn(f"Reconnect unexpected error: {e}")
                time.sleep(5)

        raise TimeoutError("BMC failed to come back online after update.")
    def _extract_ver_from_busctl(self, output):
        m = re.search(r'"([^"]+)"', output)
        return m.group(1) if m else "Unknown"