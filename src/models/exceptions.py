class AutoVerifyError(Exception):
    """專案的基礎錯誤類別"""
    pass

class ConnectionError(AutoVerifyError):
    """SSH 或 Redfish 連線失敗"""
    pass

class TimeoutError(AutoVerifyError):
    """操作超時 (如等待 Prompt 或等待更新結束)"""
    pass

class UpdateFailedError(AutoVerifyError):
    """更新過程中發生錯誤 (如 ApplyFailed)"""
    pass

class VerificationError(AutoVerifyError):
    """版本比對不符"""
    pass

class PFRViolationError(AutoVerifyError):
    """PFR 稽核失敗 (偵測到還原事件)"""
    pass