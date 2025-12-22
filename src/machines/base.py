from abc import ABC, abstractmethod

class MachineVerifier(ABC):
    def __init__(self, components):
        self.components = components

    @abstractmethod
    def verify_system(self):
        pass