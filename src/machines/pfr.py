from src.machines.base import MachineVerifier
from src.core.engine import UpdateEngine
from src.core.logger import section # [新增] 引入 section

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
                # [修改] 使用 section 顯示大標題
                section(f"Updating Component: {comp.name}")
                
                engine = UpdateEngine(comp)
                engine.execute()
                
            except Exception as e:
                print(f"[ERROR] {comp.name} failed: {e}")
                import traceback
                traceback.print_exc()
                failed_components.append(comp.name)

        # 2. PFR 稽核
        # 這裡也可以加一個 Section 區隔
        section("Starting PFR Security Audit")
        
        is_healthy, reason = self.pfr_auditor.check_health()
        
        if not is_healthy:
            raise Exception(f"PFR Security Violation: {reason}")
            
        if failed_components:
            raise Exception(f"Components failed to update: {failed_components}")

        print(" PFR System Verification Passed.")