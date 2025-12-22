from src.core.logger import info, error, step
from src.components.base import FirmwareComponent
from src.models.exceptions import VerificationError, UpdateFailedError

class UpdateEngine:
    def __init__(self, component: FirmwareComponent):
        self.component = component

    def execute(self):
        name = self.component.name
        target_ver = self.component.config.version

        info(f"=== Starting Engine for {name} ===")

        # Step 1: Pre-check
        step(1, f"Pre-check current version for {name}")
        try:
            current_ver = self.component.get_current_version()
            info(f"Current Version: {current_ver}")
        except Exception as e:
            error(f"Failed to get version: {e}")
            raise

        # Step 2: Upload
        step(2, f"Upload firmware: {self.component.config.file}")
        try:
            self.component.upload_firmware()
            info("Upload command sent successfully.")
        except Exception as e:
            error(f"Upload failed: {e}")
            raise UpdateFailedError(f"Upload stage failed for {name}")

        # Step 3: Monitor
        step(3, "Monitor update progress")
        try:
            self.component.monitor_update()
            info("Update process completed.")
        except Exception as e:
            error(f"Monitor failed: {e}")
            raise UpdateFailedError(f"Monitor stage failed for {name}")

        # Step 4: Verify
        step(4, "Verify final version")
        try:
            self.component.verify_update()
            info(f"[bold green]SUCCESS: {name} is now at version {target_ver}[/bold green]")
        except VerificationError as e:
            error(f"Verification failed: {e}")
            raise