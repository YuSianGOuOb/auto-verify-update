# src/machines/pfr.py
from src.machines.base import MachineVerifier
from src.core.engine import UpdateEngine # [FIX] 記得 import

class PFRMachineVerifier(MachineVerifier):
    def __init__(self, components, pfr_auditor):
        super().__init__(components)
        self.pfr_auditor = pfr_auditor

    def verify_system(self):
        print("=== [PFR Mode] Starting System Verification ===")
        
        # 1. 執行標準更新 (BIOS/CPLD)
        failed_components = []
        for comp in self.components:
            try:
                # [FIX] 使用 Engine 來執行流程
                print(f">>> Updating {comp.name}...")
                engine = UpdateEngine(comp)
                engine.execute()
                
            except Exception as e:
                print(f"[ERROR] {comp.name} failed: {e}")
                import traceback
                traceback.print_exc()
                failed_components.append(comp.name)

        # 2. PFR 稽核
        is_healthy, reason = self.pfr_auditor.check_health()
        
        if not is_healthy:
            raise Exception(f"PFR Security Violation: {reason}")
            
        if failed_components:
            raise Exception(f"Components failed to update: {failed_components}")

        print("✅ PFR System Verification Passed.")