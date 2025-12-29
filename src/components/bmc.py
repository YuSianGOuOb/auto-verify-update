from src.components.base import FirmwareComponent
from src.core.logger import info, error, warn, section
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
        print(json.dumps(result, indent=4))
        
        if "Id" in result:
             info(f"Task Created: ID = {result['Id']}")

    def monitor_update(self):
        apply_time = self.config.apply_time
        preserve = self.config.preserve
        
        info(f"Monitoring BMC update (Policy: {apply_time}, Preserve: {preserve})...")
        
        timeout = 600
        start_time = time.time()
        stage_completed = False
        
        # === Phase 1: 等待 Staging 完成 (或 Immediate 的生效) ===
        while time.time() - start_time < timeout:
            try:
                self.ssh.send_command("echo check", timeout=5)
                logs = self._fetch_new_logs()
                
                # 檢查是否有失敗訊息
                if "ApplyFailed" in logs or "FlashFailed" in logs:
                    error(f"Update Failed Logs: {logs}")
                    raise UpdateFailedError("BMC Update Failed during staging.")

                # 分策略檢查成功訊號
                if apply_time == "Immediate":
                    if "UpdateSuccessful" in logs:
                        info("[bold green]Log: UpdateSuccessful found! (Immediate)[/bold green]")
                        stage_completed = True
                        break
                
                elif apply_time == "OnReset":
                    # OnReset 不會立刻出現 UpdateSuccessful，而是出現 AwaitToActivate (或是 Task 完成)
                    if "AwaitToActivate" in logs or "UpdateStaged" in logs:
                        info("[bold green]Log: Firmware Staged successfully (AwaitToActivate).[/bold green]")
                        stage_completed = True
                        break
                    # 如果真的抓不到 Log，也可以考慮檢查 Redfish Task State (需實作)，這裡暫時依賴 Log

            except (paramiko.ssh_exception.SSHException, OSError, ConnectionResetError):
                # 斷線處理
                if apply_time == "Immediate":
                    info("[bold green]Connection lost (Auto Reboot detected).[/bold green]")
                    self._handle_reconnect(preserve)
                    return # Immediate 斷線重連後就結束了 (Verify 在 engine 做)
                else:
                    warn(f"[Unexpected] Connection lost but ApplyTime is '{apply_time}'!")
                    self._handle_reconnect(preserve)
                    return # 異常斷線，但也只能繼續

            except Exception:
                time.sleep(5)
            
            time.sleep(5)

        if not stage_completed:
            raise TimeoutError(f"Staging verification timed out (ApplyTime={apply_time}).")

        # === Phase 2: 執行重開機 (針對 OnReset 或 Immediate 沒自動重開的情況) ===
        
        info(f"Staging complete. Proceeding with reboot strategy for '{apply_time}'...")

        if apply_time == "Immediate":
            # Immediate 理應已經重開，如果還沒，等一下看看
            info("Waiting 30s for auto-reboot...")
            time.sleep(30)
            try:
                self.ssh.send_command("echo check", timeout=5)
                warn("BMC did NOT auto-reboot. Forcing manual reboot...")
                self.reboot_bmc()
            except:
                info("BMC auto-rebooted.")
            
            self._handle_reconnect(preserve)

        elif apply_time == "OnReset":
            # OnReset 必須手動重開
            info("Initiating MANUAL REBOOT to apply firmware (OnReset)...")
            self.reboot_bmc()
            
            # 等待重開機與連線恢復
            self._handle_reconnect(preserve)
            
            # === Phase 3: 重開機後的確認 (僅限 OnReset) ===
            # 因為 OnReset 的 Success Log 是在重開機後才寫入的
            if preserve:
                info("Checking for 'UpdateSuccessful' log after reboot...")
                # 這裡要稍微等一下，讓 BMC 有時間寫 Log
                time.sleep(20) 
                logs = self._fetch_new_logs() # 抓取最新的 Log
                
                if "UpdateSuccessful" in logs:
                     info("[bold green]Final Confirmation: UpdateSuccessful found in logs.[/bold green]")
                else:
                     warn("Could not find 'UpdateSuccessful' in logs after reboot. Please verify version manually.")
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