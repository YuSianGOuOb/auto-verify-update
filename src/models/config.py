from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

# === 連線設定 ===
class ConnectionConfig(BaseModel):
    ip: str
    user: str
    pass_: str = Field(..., alias="pass")  # 處理 yaml 中的 'pass' 關鍵字
    root_pass: Optional[str] = None

# === PFR 設定 (唯讀稽核用) ===
class PFRConfig(BaseModel):
    check_health: bool = True
    interface: str = "redfish" # redfish 或 ipmi

# === 單一元件更新設定 ===
class UpdateConfig(BaseModel):
    name: str
    type: str          # BIOS, BMC, CPLD, PFR
    subtype: Optional[str] = None  # 用於 CPLD (MB, FAN...)
    version: str
    file: Optional[str] = None     # PFR 模式下可能不需要檔案
    
    apply_time: str = "Immediate"
    preserve: bool = True
    
    # PFR 模式專用：預期下游元件的版本
    expectations: Optional[Dict[str, str]] = {} 

# === 系統層級設定 ===
class SystemConfig(BaseModel):
    profile: str
    type: str = "Standard"  # Standard 或 PFR
    connection: ConnectionConfig
    pfr: Optional[PFRConfig] = None

# === 根設定 (inventory.yaml 對應) ===
class Inventory(BaseModel):
    system: SystemConfig
    updates: List[UpdateConfig]