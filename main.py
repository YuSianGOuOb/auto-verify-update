import sys
import argparse
import yaml
import traceback
import logging
from rich.console import Console
from rich.table import Table
from rich.text import Text  # [新增] 用於處理帶顏色的版本字串

# 模型與驅動
from src.models.config import Inventory
from src.drivers.ssh import SSHClient
from src.drivers.redfish import RedfishClient
from src.components.factory import ComponentFactory
from src.components.pfr import PFRComponent
from src.machines.pfr import PFRMachineVerifier
from src.machines.standard import StandardMachineVerifier

# 引入新的 Logger 和 Section 工具
from src.core.logger import error, info, setup_logger, section

# [新增] 引入自定義 Exception
from src.models.exceptions import VerificationSkipped

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
    parser.add_argument(
        "-v", "--verify", 
        action="store_true", 
        help="Only verify current versions via D-Bus (Skip Update)"
    )
    args = parser.parse_args()

    # 1. 初始化 Logger
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
        # [分支 A] -v 模式 (只驗證不更新)
        # ==========================================
        if args.verify:
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
                    comp = ComponentFactory.create(update_cfg, drivers)
                    
                    # [修正] 取得版本字串 (可能包含顏色與 Primary 標註)
                    # 例如: "3.24.00 ([yellow]Primary[/yellow])"
                    raw_current = comp.get_current_version(quiet=True).strip()
                    expected = update_cfg.version.strip()
                    
                    # [關鍵邏輯] 去除顏色並切割，只比對純版號
                    # 1. 去除 Rich 標籤 -> "3.24.00 (Primary)"
                    plain_text = Text.from_markup(raw_current).plain
                    # 2. 取空白鍵前的部分 -> "3.24.00"
                    real_ver = plain_text.split(" ")[0].strip()

                    if real_ver == expected:
                        status = "[green]✅ PASS[/green]"
                    else:
                        status = "[bold red]❌ MISMATCH[/bold red]"
                        all_match = False
                    
                    # 表格顯示原始豐富資訊，但比對結果是正確的
                    table.add_row(update_cfg.name, raw_current, expected, status)
                
                except Exception as e:
                    table.add_row(update_cfg.name, "[red]Error[/red]", update_cfg.version, f"[red]{str(e)}[/red]")
                    all_match = False
            
            console.print(table)
            sys.exit(0 if all_match else 1)

        # ==========================================
        # [分支 B] 正常模式 (更新 + 驗證)
        # ==========================================
        info("Starting full update process...")

        components = []
        for update_cfg in config.updates:
            comp = ComponentFactory.create(update_cfg, drivers)
            components.append(comp)

        if config.system.type == "PFR":
            info("Detected PFR System. Initializing PFR logic...")
            pfr_auditor = PFRComponent(drivers)
            machine = PFRMachineVerifier(components, pfr_auditor)
        else:
            info("Detected Standard System.")
            machine = StandardMachineVerifier(components)

        machine.verify_system()

    # [新增] 捕捉 VerificationSkipped 以優雅中止 (防止被下方的 Exception 抓到)
    except VerificationSkipped as e:
        section("MANUAL ACTION REQUIRED")
        info(f"[yellow]{e}[/yellow]")
        info("[yellow]Automated verification stopped. Please verify system status manually.[/yellow]")
        sys.exit(0)

    except Exception as e:
        error(f"Execution Failed: {e}")
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