from src.components.base import FirmwareComponent
from src.core.logger import info, error, info_block, warn
from src.models.exceptions import TimeoutError, UpdateFailedError
import time
import paramiko

class BMCComponent(FirmwareComponent):
    SERVICE = "xyz.openbmc_project.Software.BMC.Updater"
    # Built-in Fallback Defaults
    DEFAULT_PRI = "/xyz/openbmc_project/software/BMCPrimary"
    DEFAULT_SEC = "/xyz/openbmc_project/software/BMCSecondary"

    def get_current_version(self, quiet=False):
        self.wait_for_bmc_ready(quiet=True)

        # [Use unpacked parameters from self]
        pri_path = self.primary_path or self.DEFAULT_PRI
        sec_path = self.secondary_path or self.DEFAULT_SEC

        # 1. Determine Boot Source
        try:
            raw_source = self.ssh.send_command("/usr/bin/processBootInfo -i").strip()
            if "Alternate" in raw_source or "Secondary" in raw_source:
                boot_source = "Secondary"
                source_color = "magenta"
            else:
                boot_source = "Primary"
                source_color = "yellow"
        except Exception:
            boot_source = "Unknown"
            source_color = "red"

        # 2. Read Versions
        pri_ver = self._get_ver_from_dbus(pri_path)
        
        # Only check secondary if sec_path is set (and valid)
        if self.secondary_path:
            sec_ver = self._get_ver_from_dbus(sec_path)
        else:
            sec_ver = "N/A"

        if not quiet:
            info(f"BMC Versions - Primary: [cyan]{pri_ver}[/cyan], Secondary: [dim]{sec_ver}[/dim]")
            info(f"Active Boot Source: [bold {source_color}]{boot_source}[/bold {source_color}]")

        if boot_source == "Secondary" and self.secondary_path:
            final_ver = sec_ver
        else:
            final_ver = pri_ver

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
        endpoint = self.update_endpoint
        
        # [Use unpacked payload]
        result = self.redfish.post_file(
            endpoint=endpoint,
            file_path=self.config.file,
            payload=self.payload
        )
        
        import json
        info("Upload Response:")
        info_block(json.dumps(result, indent=4), title="Upload Response")
        if "Id" in result:
             info(f"Task Created: ID = {result['Id']}")

    def monitor_update(self):
        # [Use unpacked parameters]
        info(f"Monitoring BMC update (ApplyTime: {self.apply_time}, Timeout: {self.timeout}s)...")
        
        start_time = time.time()
        ready_to_reboot = False      
        auto_reboot_detected = False 

        while time.time() - start_time < self.timeout:
            try:
                self.ssh.send_command("echo check", timeout=5)
                
                if self.apply_time == "OnReset":
                    logs = self._fetch_new_logs()
                    if "AwaitToActivate" in logs or "UpdateStaged" in logs:
                        info("[bold green]Log: Firmware Staged (Ready to Reboot).[/bold green]")
                        ready_to_reboot = True
                        break
                    if "ApplyFailed" in logs:
                         raise UpdateFailedError("BMC Update Failed.")

            except (paramiko.ssh_exception.SSHException, OSError, ConnectionResetError):
                if self.apply_time == "Immediate":
                    info("[bold green]Connection lost (Auto Reboot detected).[/bold green]")
                    auto_reboot_detected = True
                    break 
                else:
                    warn(f"Connection lost but ApplyTime is '{self.apply_time}'!")
                    self._handle_reconnect()
                    return 

            time.sleep(5)

        if self.apply_time == "OnReset" and not ready_to_reboot:
             raise TimeoutError("Timed out waiting for OnReset staging signal.")
        
        self._handle_reconnect()

        if self.apply_time == "OnReset":
            info("Initiating MANUAL REBOOT...")
            self.reboot_bmc()
            self._handle_reconnect()

        if self.preserve:
            info("Verifying Update Status (Post-Reboot)...")
            time.sleep(20) 
            logs = self._fetch_new_logs()
            if "UpdateSuccessful" in logs:
                 info_block(logs, title="Success Log Found")
                 self.check_system_logs()
            else:
                 warn("No 'UpdateSuccessful' log found.")
                 self.check_system_logs()
        else:
            info("Preserve is False. Skipping post-reboot log check.")

    def _handle_reconnect(self):
        """Handle reconnection logic after disconnection"""
        if self.preserve:
            self.wait_for_reboot()
        else:
            info("[yellow]Preserve is False: Credentials/IP may have changed.[/yellow]")
            info("Skipping auto-reconnect. Please verify system status manually.")