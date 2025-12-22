import sys
import argparse
import yaml
import traceback
# [FIX] 引入 Inventory 模型
from src.models.config import Inventory
from src.drivers.ssh import SSHClient
from src.drivers.redfish import RedfishClient
from src.components.factory import ComponentFactory
from src.components.pfr import PFRComponent
from src.machines.pfr import PFRMachineVerifier
from src.machines.standard import StandardMachineVerifier
from src.core.logger import error

def load_config(path):
    try:
        with open(path, 'r') as f:
            data = yaml.safe_load(f)
        # [FIX] 改用 Inventory 來解析整個 yaml 結構
        return Inventory(**data)
    except FileNotFoundError:
        error(f"Config file not found: {path}")
        sys.exit(1)
    except Exception as e:
        error(f"Invalid config format: {e}")
        # 印出詳細錯誤以便除錯
        # traceback.print_exc() 
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="Auto Verify Update Tool")
    parser.add_argument(
        "-c", "--config", 
        default="config/inventory.yaml", 
        help="Path to the inventory config file"
    )
    args = parser.parse_args()

    config = load_config(args.config)
    
    # 存取路徑不變，因為 Inventory 物件下就有 system
    conn = config.system.connection

    # 1. 初始化驅動
    ssh = SSHClient(conn.ip, conn.user, conn.pass_, conn.root_pass)
    redfish = RedfishClient(conn.ip, conn.user, conn.pass_)
    
    drivers = type('Drivers', (), {'ssh': ssh, 'redfish': redfish})()

    try:
        ssh.connect()

        # 2. 建立組件
        components = []
        for update_cfg in config.updates:
            comp = ComponentFactory.create(update_cfg, drivers)
            components.append(comp)

        # 3. 根據機種選擇驗證策略
        if config.system.type == "PFR":
            pfr_auditor = PFRComponent(drivers)
            machine = PFRMachineVerifier(components, pfr_auditor)
        else:
            machine = StandardMachineVerifier(components)

        # 4. 執行
        machine.verify_system()

    except Exception as e:
        error(f"Execution Failed: {e}")
        traceback.print_exc()
        sys.exit(1)
    finally:
        if 'ssh' in locals():
            ssh.close()

if __name__ == "__main__":
    main()