import sys
import argparse
import yaml
import traceback
import logging
from rich.console import Console
from rich.table import Table

# 模型與驅動
from src.models.config import Inventory
from src.drivers.ssh import SSHClient
from src.drivers.redfish import RedfishClient
from src.components.factory import ComponentFactory
from src.components.pfr import PFRComponent
from src.machines.pfr import PFRMachineVerifier
from src.machines.standard import StandardMachineVerifier
# [FIX] 引入新的 setup_logger
from src.core.logger import error, info, setup_logger

def load_config(path):
    try:
        with open(path, 'r') as f:
            data = yaml.safe_load(f)
        return Inventory(**data)
    except FileNotFoundError:
        error(f"Config file not found: {path}")
        sys.exit(1)
    except Exception as e:
        error(f"Invalid config format: {e}")
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="Auto Verify Update Tool")
    parser.add_argument(
        "-c", "--config", 
        default="config/inventory.yaml", 
        help="Path to the inventory config file"
    )
    # [新增] -v 參數 (只驗證不更新)
    parser.add_argument(
        "-v", "--verify", 
        action="store_true", 
        help="Only verify current versions via D-Bus (Skip Update)"
    )
    args = parser.parse_args()

    # 1. 初始化 Logger (這會把 Paramiko 設為 CRITICAL 靜音)
    setup_logger()

    config = load_config(args.config)
    conn = config.system.connection

    # 2. 初始化驅動
    ssh = SSHClient(conn.ip, conn.user, conn.pass_, conn.root_pass)
    redfish = RedfishClient(conn.ip, conn.user, conn.pass_)
    
    drivers = type('Drivers', (), {'ssh': ssh, 'redfish': redfish})()

    try:
        # 建立 SSH 連線
        ssh.connect()

        # ==========================================
        # [分支 A] 如果是 -v 模式，只檢查版本並畫表格
        # ==========================================
        if args.verify:
            # 這裡建立一個新的 console 來畫表，不受 logging 格式影響
            console = Console()
            info("Running in [bold cyan]VERIFICATION ONLY[/bold cyan] mode...")
            
            table = Table(title=f"System Verification Status ({config.system.type})")
            table.add_column("Component", style="cyan")
            table.add_column("Current Version (D-Bus)", style="magenta")
            table.add_column("Expected (Config)", style="green")
            table.add_column("Status", justify="center")

            all_match = True

            for update_cfg in config.updates:
                try:
                    # 利用工廠建立元件
                    comp = ComponentFactory.create(update_cfg, drivers)
                    
                    # 取得版本 (並去除空白)
                    current = comp.get_current_version().strip()
                    expected = update_cfg.version.strip()
                    
                    if current == expected:
                        status = "[green]✅ PASS[/green]"
                    else:
                        status = "[bold red]❌ MISMATCH[/bold red]"
                        all_match = False
                    
                    table.add_row(update_cfg.name, current, expected, status)
                
                except Exception as e:
                    table.add_row(update_cfg.name, "[red]Error[/red]", update_cfg.version, f"[red]{str(e)}[/red]")
                    all_match = False
            
            console.print(table)
            
            # 根據結果決定 Exit Code (方便 CI/CD 整合)
            sys.exit(0 if all_match else 1)

        # ==========================================
        # [分支 B] 正常模式 (更新 + 驗證)
        # ==========================================
        info("Starting full update process...")

        # 建立所有組件
        components = []
        for update_cfg in config.updates:
            comp = ComponentFactory.create(update_cfg, drivers)
            components.append(comp)

        # 根據機種選擇驗證策略
        if config.system.type == "PFR":
            info("Detected PFR System. Initializing PFR logic...")
            pfr_auditor = PFRComponent(drivers)
            machine = PFRMachineVerifier(components, pfr_auditor)
        else:
            info("Detected Standard System.")
            machine = StandardMachineVerifier(components)

        # 執行流程
        machine.verify_system()

    except Exception as e:
        error(f"Execution Failed: {e}")
        # 如果需要詳細除錯再打開 traceback
        # traceback.print_exc()
        sys.exit(1)
    finally:
        if 'ssh' in locals():
            try:
                ssh.close()
            except:
                pass

if __name__ == "__main__":
    main()