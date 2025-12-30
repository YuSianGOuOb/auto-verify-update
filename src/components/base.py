from abc import ABC, abstractmethod
import json
import copy
import re
import os  # [修正 1] 新增 os，用於檢查檔案路徑
from src.core.logger import info, warn, error # [修正 1] 新增 error

# 引入 Mixins
from src.components.mixins.power import PowerMixin
from src.components.mixins.logging import LogMixin

class FirmwareComponent(PowerMixin, LogMixin, ABC):
    def __init__(self, drivers, config):
        self.ssh = drivers.ssh
        self.redfish = drivers.redfish
        self.name = config.name
        self.config = config # 保留原始 config 備用 (取 version, file 等)
        
        # === [核心修改] 參數解構區 ===
        strategy = config.strategy

        # 1. 基礎控制參數
        self.timeout = strategy.timeout
        # [新增] 檢查並提示 Timeout
        if self.timeout == 600: # 假設 600 是預設值
            info(f"  - Timeout: {self.timeout}s (Default)")
        else:
            info(f"  - Timeout: {self.timeout}s (Configured)")
        
        # 2. 路徑設定 (處理 Standard 雙路徑 vs PFR 單路徑)
        # 如果是 PFR 或 BIOS/CPLD，通常只設 verify_path，我們將其視為 primary
        self.primary_path = strategy.primary_path or strategy.verify_path
        self.secondary_path = strategy.secondary_path
        self.update_endpoint = strategy.update_endpoint
        # [新增] 提示 Endpoint
        if self.update_endpoint == "/redfish/v1/UpdateService/upload":
            info(f"  - Endpoint: {self.update_endpoint} (Default OpenBMC URI)")
        else:
            info(f"  - Endpoint: {self.update_endpoint}")

        # 3. Payload 載入
        self.payload = {}
        
        if strategy.payload_file:
            try:
                # 確保路徑存在
                if os.path.exists(strategy.payload_file):
                    with open(strategy.payload_file, 'r') as f:
                        self.payload = json.load(f)
                    info(f"Loaded payload from {strategy.payload_file}")
                else:
                    error(f"Payload file not found: {strategy.payload_file}")
            except Exception as e:
                error(f"Failed to load payload JSON: {e}")
        else:
            type_name = self.config.type.lower() # bmc, bios, cpld
            default_file = f"config/payloads/{type_name}_default.json"
            if os.path.exists(default_file):
                try:
                    with open(default_file, 'r') as f:
                        self.payload = json.load(f)
                    info(f"  - Payload: Auto-loaded default ({default_file})")
                except Exception as e:
                    error(f"Failed to load default payload: {e}")

        # 4. [自動解析] 從 Payload 提取控制變數 (ApplyTime, Preserve)
        # 透過遞迴搜尋，不用寫死路徑
        found_time = self._find_key_recursive(self.payload, "@Redfish.OperationApplyTime")
        self.apply_time = found_time if found_time is not None else "Immediate"
        
        found_preserve = self._find_key_recursive(self.payload, "Preserve")
        self.preserve = found_preserve if found_preserve is not None else True

        # 初始化 Mixin
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

    # === 通用工具 ===

    def _extract_version(self, output):
        m = re.search(r'"([^"]+)"', output)
        return m.group(1) if m else "Unknown"

    def _clean_staging_area(self):
        try:
            # info("Cleaning up BMC staging area...")
            self.ssh.send_command("rm -rf /tmp/images/*")
        except Exception as e:
            warn(f"Failed to clean staging area: {e}")

    def verify_update(self):
        """
        驗證更新是否成功
        """
        # [修正 3] 補上 Preserve 檢查 logic
        # 因為如果不保留設定，密碼會重置，我們無法登入去查版號
        if not self.preserve:
             from src.models.exceptions import VerificationSkipped
             raise VerificationSkipped("Non-Preserve update completed (Credentials reset).")

        self.wait_for_bmc_ready(quiet=True)
        current = self.get_current_version(quiet=True)
        target = self.config.version
        
        if target.strip() not in current.strip():
             warn(f"[Verification Mismatch] Expected '{target}', but got '{current}'.")
        else:
             info(f"Version match verified: {current}")

    # === [修正 2] 移除了 _get_payload，因為 __init__ 已經做完了 ===

    def _find_key_recursive(self, data, target_key):
        """
        [通用工具] 在巢狀字典中遞迴搜尋特定的 Key。
        一旦找到第一個符合的，就回傳其 Value。
        """
        if not isinstance(data, dict):
            return None
            
        # 1. 如果這一層就有，直接回傳
        if target_key in data:
            return data[target_key]
            
        # 2. 否則進入下一層搜尋
        for key, value in data.items():
            if isinstance(value, dict):
                result = self._find_key_recursive(value, target_key)
                if result is not None:
                    return result
                    
        # 3. 都沒找到
        return None