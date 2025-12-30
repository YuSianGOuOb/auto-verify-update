import sys
import argparse
import yaml
from rich.console import Console
from rich.table import Table
from rich.text import Text

from src.models.config import Inventory
from src.drivers.ssh import SSHClient
from src.drivers.redfish import RedfishClient
from src.components.factory import ComponentFactory
from src.components.pfr import PFRComponent
from src.machines.pfr import PFRMachineVerifier
from src.machines.standard import StandardMachineVerifier
from src.core.logger import error, info, setup_logger, section
from src.models.exceptions import VerificationSkipped

def load_config(config_path, strategy_path="config/strategies.yaml"):
    try:
        # 1. 讀取 Inventory
        with open(config_path, 'r') as f:
            inv_data = yaml.safe_load(f)

        # 2. 讀取 Strategies
        strategies = {}
        try:
            with open(strategy_path, "r") as f:
                strategies = yaml.safe_load(f).get("profiles", {})
            info(f"Loaded strategies from {strategy_path}")
        except FileNotFoundError:
            info("No strategies.yaml found, using internal defaults.")

        # 3. 合併策略
        if "updates" in inv_data:
            for item in inv_data["updates"]:
                profile_name = item.get("profile")
                
                # [情況 A] 有指定 Profile 且 找到了
                if profile_name and profile_name in strategies:
                    item["strategy"] = strategies[profile_name]
                    info(f"  [{item['name']}] Applied profile: '{profile_name}'")

                # [情況 B] 有指定 Profile 但 找不到 -> 改為 Info/Warn 並使用預設
                elif profile_name:
                    from src.core.logger import warn
                    warn(f"  [{item['name']}] Profile '{profile_name}' not found. Using DEFAULT strategy.")
                    # 這裡不 assign item["strategy"]，Pydantic 會自動建立預設值

                # [情況 C] 根本沒指定 Profile -> 使用預設
                else:
                    info(f"  [{item['name']}] No profile specified. Using DEFAULT strategy.")

        return Inventory(**inv_data)
        
    except Exception as e:
        error(f"Failed to load configuration: {e}")
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="Auto Verify Update Tool")
    parser.add_argument("-c", "--config", default="config/inventory.yaml", help="Path to the inventory config file")
    parser.add_argument("-v", "--verify", action="store_true", help="Only verify current versions via D-Bus (Skip Update)")
    args = parser.parse_args()

    setup_logger()
    config = load_config(args.config)
    conn = config.system.connection

    # 初始化驅動
    ssh = SSHClient(conn.ip, conn.user, conn.pass_, conn.root_pass)
    redfish = RedfishClient(conn.ip, conn.user, conn.pass_)
    drivers = type('Drivers', (), {'ssh': ssh, 'redfish': redfish})()

    try:
        ssh.connect()

        # 模式 A: 僅驗證 (Verification Only)
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
                    raw_current = comp.get_current_version(quiet=True).strip()
                    expected = update_cfg.version.strip()
                    
                    # 比對邏輯：去除顏色代碼與 Primary/Secondary 標記，僅比對純版號
                    plain_text = Text.from_markup(raw_current).plain
                    real_ver = plain_text.split(" ")[0].strip()

                    if real_ver == expected:
                        status = "[green]✅ PASS[/green]"
                    else:
                        status = "[bold red]❌ MISMATCH[/bold red]"
                        all_match = False
                    
                    table.add_row(update_cfg.name, raw_current, expected, status)
                except Exception as e:
                    table.add_row(update_cfg.name, "[red]Error[/red]", update_cfg.version, f"[red]{str(e)}[/red]")
                    all_match = False
            
            console.print(table)
            sys.exit(0 if all_match else 1)

        # 模式 B: 完整更新流程 (Update + Verify)
        info("Starting full update process...")
        components = [ComponentFactory.create(cfg, drivers) for cfg in config.updates]

        if config.system.type == "PFR":
            info("Detected PFR System. Initializing PFR logic...")
            machine = PFRMachineVerifier(components, PFRComponent(drivers))
        else:
            info("Detected Standard System.")
            machine = StandardMachineVerifier(components)

        machine.verify_system()

    except VerificationSkipped as e:
        section("MANUAL ACTION REQUIRED")
        info(f"[yellow]{e}[/yellow]")
        info("[yellow]Automated verification stopped. Please verify system status manually.[/yellow]")
        sys.exit(0)

    except Exception as e:
        error(f"Execution Failed: {e}")
        sys.exit(1)
        
    finally:
        if 'ssh' in locals():
            try: ssh.close()
            except: pass

if __name__ == "__main__":
    main()