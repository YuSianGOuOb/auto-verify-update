from src.machines.base import MachineVerifier
from src.core.engine import UpdateEngine
from src.core.logger import info, error, section # [新增] 引入 section

class StandardMachineVerifier(MachineVerifier):
    def verify_system(self):
        info("=== Starting Standard Machine Verification ===")
        
        all_passed = True
        results = {}

        for component in self.components:
            # [修改] 使用 section 顯示大標題
            section(f"Processing Component: {component.name}")
            
            engine = UpdateEngine(component)
            
            try:
                engine.execute()
                results[component.name] = "PASS"
            except Exception as e:
                error(f"Component {component.name} failed: {e}")
                results[component.name] = "FAIL"
                all_passed = False
        
        if not all_passed:
            raise Exception("Standard Machine Verification Failed.")