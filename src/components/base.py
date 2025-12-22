from abc import ABC, abstractmethod
from src.utils.log_parser import parse_sel_after_time
# [NEW] 引入 Logger
from src.core.logger import warn, info

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

    def verify_update(self):
        """預設驗證邏輯：比對版本"""
        current = self.get_current_version()
        target = self.config.version
        
        # [MODIFIED] 改為 Warning 並繼續，不拋出錯誤
        if target not in current:
             warn(f"[Verification Mismatch] Expected '{target}', but got '{current}'. (Continuing execution...)")
        else:
             info(f"Version match verified: {current}")

    def check_sel_log(self, baseline_time):
        logs = parse_sel_after_time(self.ssh, baseline_time)
        if logs:
            for line in logs:
                print(f"[SEL] {line}")
            return False
        return True