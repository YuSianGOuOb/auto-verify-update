import time
from src.core.logger import info, warn
from src.models.exceptions import TimeoutError

class PowerMixin:
    """負責電源控制、BMC 重啟與 Post Code 監控"""

    def host_power_off(self):
        info("Executing: ipmitool chassis power off")
        try:
            self.ssh.send_command("ipmitool chassis power off")
            time.sleep(10)
            status = self.ssh.send_command("ipmitool chassis power status")
            if "off" in status.lower():
                info("[bold green]Host Power is OFF[/bold green]")
            else:
                warn(f"Host power status is: {status}")
        except Exception as e:
            warn(f"Failed to power off host: {e}")

    def host_power_on(self):
        info("Executing: ipmitool chassis power on")
        try:
            self.ssh.send_command("ipmitool chassis power on")
        except Exception as e:
            warn(f"Failed to power on host: {e}")

    def reboot_bmc(self):
        info("Sending BMC Reboot command...")
        try:
            endpoint = "/redfish/v1/Managers/bmc/Actions/Manager.Reset"
            payload = {"ResetType": "GracefulRestart"}
            self.redfish.post_action(endpoint, payload)
            info("Redfish restart command sent.")
            return
        except Exception as e:
            warn(f"Redfish reset failed: {e}. Trying SSH...")

        try:
            self.ssh.send_command("reboot")
            info("SSH reboot command sent.")
        except Exception:
            pass

    def wait_for_reboot(self, timeout=900):
        info("Waiting for BMC to come back online...")
        start_time = time.time()
        try: self.ssh.close()
        except: pass
        time.sleep(15)

        while time.time() - start_time < timeout:
            try:
                self.ssh.connect()
                info("[bold green]SSH Connection Restored![/bold green]")
                self.wait_for_bmc_ready()
                return
            except Exception:
                time.sleep(5)
        raise TimeoutError("BMC failed to come back online (SSH unreachable).")

    def wait_for_bmc_ready(self, quiet=False):
        if not quiet: info("Checking BMC Readiness...")
        timeout = 600 
        start_time = time.time()
        logged_wait = False
        
        # Check D-Bus
        while time.time() - start_time < timeout:
            try:
                cmd = "busctl get-property xyz.openbmc_project.State.BMC /xyz/openbmc_project/state/bmc0 xyz.openbmc_project.State.BMC CurrentBMCState"
                output = self.ssh.send_command(cmd)
                if "xyz.openbmc_project.State.BMC.BMCState.Ready" in output: break
                if quiet and not logged_wait:
                    info("BMC not ready yet, waiting...")
                    logged_wait = True
                time.sleep(5)
            except: time.sleep(5)
        else:
            warn("Timeout waiting for D-Bus State 'Ready'.")

        # Check Systemd
        while time.time() - start_time < timeout:
            try:
                output = self.ssh.send_command("systemctl list-jobs")
                if "No jobs running" in output:
                    if not quiet: info("[bold green]BMC is Fully Ready.[/bold green]")
                    elif logged_wait: info("[bold green]BMC is now Ready.[/bold green]")
                    return
                if quiet and not logged_wait:
                    info("Waiting for systemd jobs...")
                    logged_wait = True
                time.sleep(5)
            except: time.sleep(5)
        warn("Timeout waiting for Systemd jobs.")

    def get_post_code(self):
        try:
            cmd = "busctl get-property xyz.openbmc_project.State.Boot.Raw /xyz/openbmc_project/state/boot/raw0 xyz.openbmc_project.State.Boot.Raw Value"
            output = self.ssh.send_command(cmd).strip()
            # info(f"output: [cyan]{output}[/cyan]") # Debug 用

            # 1. 先按行分割，避免標題列干擾
            for line in output.splitlines():
                line = line.strip()
                
                # 2. 針對每一行判斷
                if "(ayay)" in line:
                    # 去掉 (ayay) 後切割: "1 175 0" -> ["1", "175", "0"]
                    parts = line.replace("(ayay)", "").strip().split()
                    if len(parts) >= 2: 
                        # parts[1] 才是真正的數值
                        code = hex(int(parts[1]))
                        # info(f"POST Code: [cyan]{code}[/cyan]")
                        return code
                        
                elif "t " in line: # 處理 t 格式
                     if line.startswith("t "): # 確保是開頭
                        val_str = line.split("t ")[1].strip()
                        return hex(int(val_str))

        except Exception as e:
            # warn(f"Get Post Code Failed: {e}") # 建議把錯誤印出來方便除錯
            pass
            
        return "Unknown"

    def wait_for_host_boot(self, timeout=900):
        info("Waiting for Host to boot (Monitoring POST Codes)...")
        start_time = time.time()
        
        stale_code = self.get_post_code()
        if stale_code != "Unknown":
            info(f"Initial (Stale) Post Code: [dim]{stale_code}[/dim]")
        
        last_code = stale_code
        boot_active = False
        
        while time.time() - start_time < timeout:
            code = self.get_post_code()
            if code != "Unknown" and code != last_code:
                # info(f"POST Code: [cyan]{code}[/cyan]")
                last_code = code
                boot_active = True

            if boot_active and code == "0xaa":
                info("[bold green]Target POST Code 0xaa reached![/bold green]")
                return
            
            time.sleep(2)

        warn("Timeout waiting for Host Boot.")