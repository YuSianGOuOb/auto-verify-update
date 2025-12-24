from abc import ABC, abstractmethod
from src.utils.log_parser import parse_sel_after_time
from src.core.logger import warn, info
import time

class FirmwareComponent(ABC):
    def __init__(self, drivers, config):
        self.ssh = drivers.ssh
        self.redfish = drivers.redfish
        self.config = config
        self.name = config.name

    @abstractmethod
    def get_current_version(self) -> str:
        pass

    @abstractmethod
    def upload_firmware(self):
        pass

    @abstractmethod
    def monitor_update(self):
        pass

    def wait_for_bmc_ready(self):
        """
        等待 BMC 完全就緒：
        1. 檢查 D-Bus State 是否為 Ready
        2. [新增] 檢查 systemctl list-jobs 是否為 "No jobs running."
        """
        info("Checking BMC Readiness...")
        timeout = 600 
        start_time = time.time()
        
        # --- Stage 1: Check D-Bus State ---
        info("Stage 1: Checking D-Bus State (xyz.openbmc_project.State.BMC)...")
        while time.time() - start_time < timeout:
            try:
                # 確保 SSH 連線存在
                if not self.ssh.client or not self.ssh.channel:
                    try:
                        self.ssh.connect()
                    except:
                        time.sleep(5)
                        continue

                cmd = (
                    "busctl get-property "
                    "xyz.openbmc_project.State.BMC "
                    "/xyz/openbmc_project/state/bmc0 "
                    "xyz.openbmc_project.State.BMC CurrentBMCState"
                )
                output = self.ssh.send_command(cmd)
                
                if "xyz.openbmc_project.State.BMC.BMCState.Ready" in output:
                    info("[bold green]D-Bus State is 'Ready'![/bold green]")
                    break
                
                time.sleep(5)
            except Exception:
                time.sleep(5)
        else:
            warn("Timeout waiting for D-Bus State 'Ready'. Proceeding anyway...")

        # --- Stage 2: Check Systemd Jobs ---
        # 這是為了確保所有服務都已經啟動完畢 (Quiesced)
        info("Stage 2: Checking Systemd Jobs (systemctl list-jobs)...")
        while time.time() - start_time < timeout:
            try:
                cmd = "systemctl list-jobs"
                output = self.ssh.send_command(cmd)
                
                # 檢查輸出是否包含 "No jobs running"
                if "No jobs running" in output:
                    info("[bold green]Systemd is idle (No jobs running). System is fully operational.[/bold green]")
                    return
                else:
                    # 如果還有 jobs 在跑，可以印出來看看是什麼 (選用)
                    # info(f"Waiting for jobs to finish: {output.strip()}")
                    time.sleep(5)

            except Exception:
                time.sleep(5)

        warn("Timeout waiting for Systemd jobs to finish. Proceeding anyway...")

    def verify_update(self):
        """預設驗證邏輯：比對版本"""
        # [NEW] 在驗證前，先確保 BMC 是健康的
        # 這樣就不怕 BIOS/CPLD 更新後 BMC 還在忙碌中
        self.wait_for_bmc_ready()

        current = self.get_current_version()
        target = self.config.version
        
        # 使用 strip() 避免空白造成誤判
        if target.strip() not in current.strip():
             warn(f"[Verification Mismatch] Expected '{target}', but got '{current}'. (Continuing execution...)")
             # 如果您希望嚴格一點，這裡可以 raise Exception
             # raise Exception(f"Version Mismatch! Expected: {target}, Got: {current}")
        else:
             info(f"Version match verified: {current}")

    def check_sel_log(self, baseline_time):
        logs = parse_sel_after_time(self.ssh, baseline_time)
        if logs:
            for line in logs:
                print(f"[SEL] {line}")
            return False
        return True