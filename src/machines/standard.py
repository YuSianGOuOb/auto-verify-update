from src.machines.base import MachineVerifier
from src.core.engine import UpdateEngine
from src.core.logger import info, error

class StandardMachineVerifier(MachineVerifier):
    def verify_system(self):
        info("=== Starting Standard Machine Verification ===")
        
        all_passed = True
        results = {}
        driver_ref = self.components[0] if self.components else None
        driver_ref.wait_for_bmc_ready()

        for component in self.components:
            info(f"\n>>> Processing Component: {component.name} <<<")
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