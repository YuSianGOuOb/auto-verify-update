from abc import ABC, abstractmethod
import re
from src.core.logger import info, warn
# 引入 Mixins
from src.components.mixins.power import PowerMixin
from src.components.mixins.logging import LogMixin

class FirmwareComponent(PowerMixin, LogMixin, ABC):
    def __init__(self, drivers, config):
        self.ssh = drivers.ssh
        self.redfish = drivers.redfish
        self.config = config
        self.name = config.name
        
        # 初始化 Mixin 需要的變數
        self.init_log_baselines()

    @abstractmethod
    def get_current_version(self, quiet=False) -> str:
        pass

    @abstractmethod
    def upload_firmware(self):
        pass

    @abstractmethod
    def monitor_update(self):
        pass

    # === 通用工具 (不適合放在 Power 或 Log 的零散工具) ===

    def _extract_version(self, output):
        m = re.search(r'"([^"]+)"', output)
        return m.group(1) if m else "Unknown"

    def _clean_staging_area(self):
        try:
            info("Cleaning up BMC staging area...")
            self.ssh.send_command("rm -rf /tmp/images/*")
        except Exception as e:
            warn(f"Failed to clean staging area: {e}")

    def verify_update(self):
        self.wait_for_bmc_ready(quiet=True)
        current = self.get_current_version(quiet=True)
        target = self.config.version
        
        if target.strip() not in current.strip():
             warn(f"[Verification Mismatch] Expected '{target}', but got '{current}'.")
        else:
             info(f"Version match verified: {current}")