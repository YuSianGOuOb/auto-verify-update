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
        # [NEW] 1. 清理 BMC 暫存區 (防止空間不足或舊檔干擾)
        try:
            info("Cleaning up BMC staging area (/tmp/images)...")
            # rm -rf 不會報錯即使目錄為空，非常安全
            # 注意：OpenBMC 的上傳路徑通常是 /tmp/images，如果不確定，清 /tmp 裡的特定檔案也可
            self.ssh.send_command("rm -rf /tmp/images/*")
        except Exception as e:
            # 清理失敗不應該阻擋流程，印個警告就好
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
        
        # 3. 執行上傳
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

# [新增] 用於發送 Redfish 重開機指令
    def reboot_bmc(self):
        info("Sending Redfish Force Restart command...")
        try:
            # 標準 Redfish BMC 重開機路徑
            # 如果是特定機種，Manager ID 可能是 'bmc' 或 '1'，通常 'bmc' 是通用的
            endpoint = "/redfish/v1/Managers/bmc/Actions/Manager.Reset"
            payload = {
                "ResetType": "GracefulRestart"
            }
            # 使用 requests 發送 (因為這是簡單的指令，不需要用 curl)
            self.redfish.post_action(endpoint, payload)
        except Exception as e:
            warn(f"Failed to send Redfish reset: {e}")
            # 如果 Redfish 失敗，嘗試用 SSH 重開作為備案
            try:
                self.ssh.send_command("reboot")
            except:
                pass

    def monitor_update(self):
        info("Monitoring BMC update (Hybrid: Log Scan + Auto/Manual Reboot)...")
        
        timeout = 600
        start_time = time.time()
        
        # 標記是否已經偵測到重開機
        reboot_started = False
        # 標記是否已經看到成功訊息
        update_success_found = False
        
        while time.time() - start_time < timeout:
            try:
                # --- 1. 檢查 SSH 連線是否還活著 ---
                try:
                    self.ssh.send_command("echo check", timeout=5)
                except Exception:
                    # 發生異常代表斷線了 -> 重開機開始！
                    info("[bold yellow]SSH Connection lost. Reboot initiated![/bold yellow]")
                    reboot_started = True
                    break

                # --- 2. 如果還沒斷線，檢查 Log ---
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
                    
                    # 看到成功後，給它 30 秒自己重開
                    info("Waiting 30s for automatic reboot...")
                    time.sleep(30)
                    
                    # 30秒後再次檢查連線
                    try:
                        self.ssh.send_command("echo check", timeout=5)
                        # 如果還能執行指令，代表沒重開 -> 我們手動踢它
                        info("[bold yellow]BMC did not reboot automatically. Forcing reboot...[/bold yellow]")
                        self.reboot_bmc()
                    except Exception:
                        # 已經斷線了，那就不做動作，讓迴圈下一次自然 break
                        pass

            except Exception as e:
                # 這裡的 Exception 通常是上面 SSH check 拋出的
                if not reboot_started:
                    info(f"[bold yellow]Connection dropped ({e}). Reboot started![/bold yellow]")
                    reboot_started = True
                    break

            time.sleep(5)

        # --- 階段 2: 等待連線恢復 ---
        if not reboot_started:
            # 如果跑到這裡還沒斷線，通常是 timeout 或強制重開失敗
            warn("Timeout reached without detecting reboot. BMC might be stuck.")

        info("Waiting for BMC to come back online...")
        reconnect_timeout = 600
        start_reconnect = time.time()
        
        while time.time() - start_reconnect < reconnect_timeout:
            try:
                self.ssh.close()
                time.sleep(5)
                self.ssh.connect()
                
                info("[bold green]BMC is back online and SSH re-established![/bold green]")
                time.sleep(10)
                return
            except Exception:
                time.sleep(10)

        raise TimeoutError("BMC failed to come back online after update.")

    def _extract_ver_from_busctl(self, output):
        m = re.search(r'"([^"]+)"', output)
        return m.group(1) if m else "Unknown"