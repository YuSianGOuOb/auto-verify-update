from src.core.logger import info, info_block, warn, error

class LogMixin:
    """負責 Log 基準線紀錄與檢查"""

    def init_log_baselines(self):
        self.log_baseline = 0
        self.sel_baseline = 0

    def _record_log_baseline(self):
        # Redfish Baseline
        try:
            cmd = "wc -l /var/log/redfish | awk '{print $1}'"
            self.log_baseline = int(self.ssh.send_command(cmd).strip())
            info(f"Log Baseline: {self.log_baseline}")
        except: 
            self.log_baseline = 0

        # SEL Baseline
        try:
            cmd = "ipmitool sel list | wc -l"
            self.sel_baseline = int(self.ssh.send_command(cmd).strip())
            info(f"SEL Baseline: {self.sel_baseline}")
        except:
            self.sel_baseline = 0

    def _fetch_new_logs(self):
        try:
            count = int(self.ssh.send_command("wc -l /var/log/redfish | awk '{print $1}'").strip())
            if self.log_baseline > 0 and count >= self.log_baseline:
                return self.ssh.send_command(f"tail -n +{self.log_baseline + 1} /var/log/redfish")
            return self.ssh.send_command("tail -n 50 /var/log/redfish")
        except: return ""

    def check_system_logs(self):
        info("Checking System Logs...")
        try:
            curr_sel = int(self.ssh.send_command("ipmitool sel list | wc -l").strip())
            if self.sel_baseline >= 0 and curr_sel > self.sel_baseline:
                diff = curr_sel - self.sel_baseline
                new_sel = self.ssh.send_command(f"ipmitool sel list | tail -n {diff}")
                
                # Check Version
                vers = [l for l in new_sel.splitlines() if "Version" in l]
                if vers:
                    info("--- New Version Logs (SEL) ---")
                    info_block("\n".join(vers), title="New Version Logs (SEL)")
                    info("[bold green]Version log found.[/bold green]")
                else:
                    warn("No 'Version' events in NEW SEL.")
                
                # Check Critical
                if "Critical" in new_sel or "Non-Recoverable" in new_sel:
                    error("Critical events in NEW SEL!")
                    info_block(new_sel, title="Critical Events", title_color="red")
            else:
                info("No new SEL entries.")
        except Exception as e:
            warn(f"Failed to check SEL: {e}")