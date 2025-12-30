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

#=== 更新策略設定 ===
class UpdateStrategy(BaseModel):
    timeout: int = 600
    primary_path: Optional[str] = None
    secondary_path: Optional[str] = None
    verify_path: Optional[str] = None # 相容舊欄位
    
    # [修改] 改為儲存檔案路徑
    payload_file: Optional[str] = None
    update_endpoint: str = "/redfish/v1/UpdateService/upload"

# === 單一元件更新設定 ===
class UpdateConfig(BaseModel):
    name: str
    type: str          # BIOS, BMC, CPLD, PFR
    version: str
    file: Optional[str] = None
    
    profile: Optional[str] = None
    strategy: UpdateStrategy = Field(default_factory=UpdateStrategy)
    
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