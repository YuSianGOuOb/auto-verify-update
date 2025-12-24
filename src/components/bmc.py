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

    # [新增] 初始化方法，確保變數一定存在
    def __init__(self, drivers, config):
        super().__init__(drivers, config)
        # 先給個預設值 0，這樣 monitor_update 就不會因為找不到變數而報錯
        self.log_baseline = 0

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
        info("Monitoring BMC update (Auto Reboot Expected)...")
        
        timeout = 600
        start_time = time.time()
        
        # 狀態標記
        reboot_detected = False
        
        # --- 階段 1: 監控直到斷線或成功 ---
        while time.time() - start_time < timeout:
            try:
                # [關鍵 1] 主動測試連線 (Heartbeat)
                # 如果這行報錯，代表 SSH 已經斷了 -> 重開機開始！
                self.ssh.send_command("echo check", timeout=5)

                # [關鍵 2] 檢查 Log (輔助)
                count_cmd = "wc -l /var/log/redfish | awk '{print $1}'"
                curr_lines = int(self.ssh.send_command(count_cmd).strip())
                
                if self.log_baseline > 0 and curr_lines >= self.log_baseline:
                    cmd = f"tail -n +{self.log_baseline + 1} /var/log/redfish"
                else:
                    cmd = "tail -n 50 /var/log/redfish"

                logs = self.ssh.send_command(cmd)

                if "UpdateSuccessful" in logs:
                    info("[bold green]Log confirms update success! Waiting for reboot...[/bold green]")
                    # 這裡不 break，繼續等斷線，或者給個 30 秒手動踢
                    time.sleep(30)
                    try:
                        self.reboot_bmc()
                    except:
                        pass # 可能已經斷了

            except (paramiko.ssh_exception.SSHException, OSError, ConnectionResetError) as e:
                # 捕捉真正的網路錯誤
                info(f"[bold yellow]Connection lost ({str(e)}). Reboot detected![/bold yellow]")
                reboot_detected = True
                break
            except Exception as e:
                # 捕捉其他程式錯誤 (例如 AttributeError)，但不當作重開機，而是印出來方便除錯
                # 除非錯誤訊息包含 "Socket is closed" 之類的
                if "Socket is closed" in str(e) or "not connected" in str(e):
                    info(f"[bold yellow]Connection lost ({str(e)}). Reboot detected![/bold yellow]")
                    reboot_detected = True
                    break
                else:
                    # 這就是之前導致誤判的地方，現在我們把它印出來而不 break
                    warn(f"Monitor loop warning: {e}")
                    time.sleep(5)
            
            time.sleep(5)

        if not reboot_detected:
            warn("Timeout waiting for reboot. System might be stuck or update failed silently.")

        # --- 階段 2: 等待連線恢復 ---
        info("Waiting for BMC to come back online...")
        reconnect_timeout = 900 # 給它多一點時間，有些機器重開很久
        start_reconnect = time.time()
        
        while time.time() - start_reconnect < reconnect_timeout:
            try:
                self.ssh.close()
                time.sleep(10)
                self.ssh.connect()
                info("[bold green]BMC is back online (SSH)![/bold green]")
                
                # 等待服務 Ready
                self.wait_for_bmc_ready()
                return
            except Exception:
                # 連線失敗是正常的，繼續等
                time.sleep(5)

        raise TimeoutError("BMC failed to come back online (SSH unreachable).")


    def _extract_ver_from_busctl(self, output):
        m = re.search(r'"([^"]+)"', output)
        return m.group(1) if m else "Unknown"