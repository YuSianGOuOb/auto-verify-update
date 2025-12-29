from src.components.base import FirmwareComponent
from src.core.logger import info, error, info_block, warn, section
from src.models.exceptions import TimeoutError, UpdateFailedError, VerificationSkipped
import time
import paramiko

class BMCComponent(FirmwareComponent):
    SERVICE = "xyz.openbmc_project.Software.BMC.Updater"
    PRIMARY_PATH = "/xyz/openbmc_project/software/BMCPrimary"
    SECONDARY_PATH = "/xyz/openbmc_project/software/BMCSecondary"

    def get_current_version(self, quiet=False):
        self.wait_for_bmc_ready(quiet=True)
        try:
            # 取得 Boot Source (Primary / Secondary / Alternate)
            # 這裡我們稍微處理一下字串，讓顯示好看一點
            raw_source = self.ssh.send_command("/usr/bin/processBootInfo -i").strip()
            
            # 判斷是哪一邊
            if "Alternate" in raw_source or "Secondary" in raw_source:
                boot_source = "Secondary"
                source_color = "magenta"
            else:
                boot_source = "Primary"
                source_color = "yellow"
                
        except Exception:
            boot_source = "Unknown"
            source_color = "red"

        # 取得雙邊版本
        pri_ver = self._get_ver_from_dbus(self.PRIMARY_PATH)
        sec_ver = self._get_ver_from_dbus(self.SECONDARY_PATH)

        if not quiet:
            info(f"BMC Versions - Primary: [cyan]{pri_ver}[/cyan], Secondary: [dim]{sec_ver}[/dim]")
            info(f"Active Boot Source: [bold {source_color}]{boot_source}[/bold {source_color}]")

        # 決定要回傳哪個版本
        if boot_source == "Secondary":
            final_ver = sec_ver
        else:
            final_ver = pri_ver

        # === [關鍵修改] 回傳格式化字串 ===
        # 回傳格式： "3.24.00 (Primary)"
        # 因為您的驗證邏輯是 check "3.24.00" inside "3.24.00 (Primary)"，所以這不會導致驗證失敗
        return f"{final_ver} ([{source_color}]{boot_source}[/{source_color}])"

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
        
        apply_time = self.config.apply_time
        preserve_cfg = self.config.preserve
        info(f"Update Parameters -> ApplyTime: [cyan]{apply_time}[/cyan], Preserve: [cyan]{preserve_cfg}[/cyan]")
        payload = {
            "UpdateParameters": {
                "@Redfish.OperationApplyTime": apply_time,
                "Oem": {"QCT_IO": {"Preserve": preserve_cfg}}
            }
        }

        result = self.redfish.post_file(
            endpoint=endpoint,
            file_path=self.config.file,
            payload=payload 
        )
        
        info("Upload Response:")
        import json
        info_block(json.dumps(result, indent=4), title="Upload Response")
        
        if "Id" in result:
             info(f"Task Created: ID = {result['Id']}")

    def monitor_update(self):
        apply_time = self.config.apply_time
        preserve = self.config.preserve
        
        info(f"Monitoring BMC update (Policy: {apply_time}, Preserve: {preserve})...")
        
        timeout = 600
        start_time = time.time()
        
        # 狀態標記
        ready_to_reboot = False      # 用於 OnReset (Log 訊號)
        auto_reboot_detected = False # 用於 Immediate (斷線訊號)

        # === Phase 1: 等待更新觸發 (Wait Phase) ===
        # Immediate: 等待斷線
        # OnReset: 等待 Staging 完成訊號
        while time.time() - start_time < timeout:
            try:
                # 保持連線活動，順便偵測斷線
                self.ssh.send_command("echo check", timeout=5)
                
                # [OnReset] 必須主動撈 Log 才知道何時可以重開機
                if apply_time == "OnReset":
                    logs = self._fetch_new_logs()
                    if "AwaitToActivate" in logs or "UpdateStaged" in logs:
                        info("[bold green]Log: Firmware Staged successfully (Ready to Reboot).[/bold green]")
                        ready_to_reboot = True
                        break
                    
                    # 快速失敗檢查
                    if "ApplyFailed" in logs or "FlashFailed" in logs:
                         raise UpdateFailedError("BMC Update Failed (Log indicates failure).")

            except (paramiko.ssh_exception.SSHException, OSError, ConnectionResetError):
                # [Immediate] 斷線就是最好的訊號
                if apply_time == "Immediate":
                    info("[bold green]Connection lost (Auto Reboot detected).[/bold green]")
                    auto_reboot_detected = True
                    break 
                else:
                    warn(f"[Unexpected] Connection lost but ApplyTime is '{apply_time}'!")
                    self._handle_reconnect(preserve)
                    return # 異常終止

            time.sleep(5)

        # === Timeout 檢查 ===
        if apply_time == "OnReset" and not ready_to_reboot:
             raise TimeoutError("Timed out waiting for OnReset staging signal.")
        
        # === Phase 2: 重開機與連線恢復 (Reboot Phase) ===
        
        # 1. 確保連線恢復 (處理 Immediate 剛才的斷線)
        self._handle_reconnect(preserve)

        # 2. 執行手動重開機 (僅 OnReset 需要)
        if apply_time == "OnReset":
            info("Initiating MANUAL REBOOT to apply firmware...")
            self.reboot_bmc()
            self._handle_reconnect(preserve) # 等待重開機完成

        # === Phase 3: 統一驗證 (Verification Phase) ===
        # 這是您最想要的部分：所有 Log 檢查都移到這裡
        
        if preserve:
            info("Verifying Update Status (Post-Reboot)...")
            
            # 給 BMC 一點時間寫入啟動 Log
            time.sleep(20) 
            
            # 這裡會一次抓取從上傳後到現在的所有 Logs
            logs = self._fetch_new_logs()
            
            # 1. 檢查更新成功訊號
            if "UpdateSuccessful" in logs:
                 info_block(logs, title="Success Log Found")
                 
                 # 2. 確認成功後，才檢查系統是否有其他錯誤 (SEL)
                 self.check_system_logs()
            else:
                 warn("Could not find 'UpdateSuccessful' in logs after reboot.")
                 # 即使沒看到成功 Log (可能被洗掉)，還是建議檢查一下 SEL 看有無 Critical
                 self.check_system_logs()
        else:
            info("Preserve is False. Skipping post-reboot log check.")

    def _handle_reconnect(self, preserve):
        """處理斷線後的重連邏輯"""
        if preserve:
            self.wait_for_reboot()
        else:
            info("[yellow]Preserve is False: Credentials/IP may have changed.[/yellow]")
            info("Skipping auto-reconnect. Please verify system status manually.")
            # 這裡不拋錯，讓程式正常結束 Monitor 階段

    def verify_update(self):
        """
        覆寫驗證邏輯：處理 Non-Preserve 的特殊情況
        """
        if not self.config.preserve:
            raise VerificationSkipped("Factory Reset confirmed (Password Change Required).")
            
        super().verify_update()