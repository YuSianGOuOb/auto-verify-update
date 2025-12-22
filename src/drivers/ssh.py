import paramiko
import time
import re

class SSHClient:
    def __init__(self, ip, user, password, root_pass):
        self.ip = ip
        self.user = user
        self.password = password
        self.root_pass = root_pass
        self.client = None
        self.channel = None

    def connect(self):
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.client.connect(self.ip, username=self.user, password=self.password)
        
        # 建立互動式 Shell
        self.channel = self.client.invoke_shell()
        self.wait_for_prompt(r"[\$#] ") # 等待登入後的 prompt

        # 切換 Root (如果還不是 root)
        self.send_command("su -", wait_for=r"Password:")
        self.send_command(self.root_pass, wait_for=r"[#\$] ")

    def wait_for_prompt(self, pattern=r"[\$#] ", timeout=30):
        return self.read_until(pattern, timeout)

    def send_command(self, cmd, wait_for=r"[#\$] ", timeout=30):
        """
        發送指令並讀取直到看見 prompt (Expect Pattern)
        徹底解決 time.sleep 不穩定的問題
        """
        if not self.channel:
            raise ConnectionError("SSH not connected")
            
        self.channel.send(cmd + "\n")
        return self.read_until(wait_for, timeout)

    def read_until(self, pattern, timeout):
        """持續讀取 buffer 直到 regex pattern 出現"""
        buffer = ""
        start = time.time()
        while time.time() - start < timeout:
            if self.channel.recv_ready():
                chunk = self.channel.recv(4096).decode('utf-8', errors='ignore')
                buffer += chunk
                if re.search(pattern, buffer):
                    return self._clean_output(buffer)
            time.sleep(0.1)
        raise TimeoutError(f"SSH Timed out waiting for pattern: {pattern}")

    def _clean_output(self, raw):
        # 這裡保留您原本去除 echo 和 prompt 的邏輯，但做得更乾淨
        lines = raw.splitlines()
        # 簡單過濾：去除頭尾的 prompt 行
        return "\n".join(lines[1:-1]).strip()

    def close(self):
        if self.client:
            self.client.close()