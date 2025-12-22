from src.components.cpld import CPLDComponent
from src.components.bios import BIOSComponent
# from src.components.bmc import BMCComponent    <-- 記得實作並 import

def create_component(config, drivers):
    if config.type == "CPLD":
        return CPLDComponent(drivers, config)
    elif config.type == "BIOS":
        return BIOSComponent(drivers, config)
        # raise NotImplementedError("BIOS component not yet implemented")
    elif config.type == "BMC":
        # return BMCComponent(drivers, config)
        raise NotImplementedError("BMC component not yet implemented")
    else:
        raise ValueError(f"Unknown component type: {config.type}")

class ComponentFactory:
    @staticmethod
    def create(config, drivers):
        return create_component(config, drivers)