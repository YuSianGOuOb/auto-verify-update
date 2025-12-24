import requests
import urllib3
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type
import os
import json
import subprocess
import tempfile

# 忽略自簽憑證警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class RedfishClient:
    def __init__(self, ip, user, password):
        self.base_url = f"https://{ip}"
        self.auth = (user, password)
        self.verify = False
        self.timeout = 30

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(2), retry=retry_if_exception_type(requests.RequestException))
    def get(self, endpoint):
        """通用 GET 請求 (維持使用 requests)"""
        url = f"{self.base_url}{endpoint}"
        response = requests.get(url, auth=self.auth, verify=self.verify, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def post_file(self, endpoint, file_path, payload=None, file_key="UpdateFile"):
        """改用 curl 來處理上傳，規避 requests 的 Multipart 相容性問題"""
        url = f"{self.base_url}{endpoint}"
        temp_param_file = None
        
        try:
            # 建構 curl 指令
            cmd = [
                "curl", "-k", "-s", "-S",
                "-u", f"{self.auth[0]}:{self.auth[1]}",
                "-X", "POST", url,
                "-F", f"{file_key}=@{file_path}"
            ]

            # 處理額外參數 (JSON)
            if payload:
                for key, value in payload.items():
                    if isinstance(value, (dict, list)):
                        # 使用 tempfile 建立唯一的暫存檔
                        # delete=False 因為 curl 需要讀取它，我們稍後手動刪除
                        with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.json') as tmp:
                            json.dump(value, tmp)
                            temp_param_file = tmp.name
                        
                        # 加入 curl 參數，指定 type=application/json
                        cmd.extend(["-F", f"{key}=@{temp_param_file};type=application/json"])
                    else:
                        cmd.extend(["-F", f"{key}={str(value)}"])

            print(f"[Redfish/Curl] Executing upload to {endpoint}...")
            # print(" ".join(cmd)) # Debug: 印出完整指令 (含密碼，請小心)

            # 執行指令
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

            if result.returncode != 0:
                print(f"[Redfish/Curl] Stderr: {result.stderr}")
                raise RuntimeError(f"Curl execution failed with code {result.returncode}")

            output = result.stdout.strip()
            if not output:
                return {"Status": "OK", "Message": "No response body"}

            try:
                response_json = json.loads(output)
                
                # 錯誤檢查邏輯
                if "error" in response_json:
                    error_obj = response_json["error"]
                    print(f"[Redfish/Curl] API Logic Error Detected: {json.dumps(error_obj, indent=2)}")
                    msg = error_obj.get("message", "Unknown Error")
                    code = error_obj.get("code", "Unknown Code")
                    raise RuntimeError(f"Redfish API Failed: [{code}] {msg}")

                return response_json
            except json.JSONDecodeError:
                if "error" in output.lower() or "invalid" in output.lower():
                     raise RuntimeError(f"Upload failed (Raw Output): {output}")
                return {"Status": "Unknown", "Raw": output}

        except subprocess.TimeoutExpired:
            print("[Redfish/Curl] Upload timed out!")
            raise
        except Exception as e:
            print(f"[Redfish/Curl] Exception: {e}")
            raise
        finally:
            # 清理暫存檔
            if temp_param_file and os.path.exists(temp_param_file):
                try:
                    os.remove(temp_param_file)
                except OSError:
                    pass

    def post_action(self, endpoint, payload):
        """執行 Action (維持使用 requests)"""
        url = f"{self.base_url}{endpoint}"
        response = requests.post(
            url, 
            json=payload, 
            auth=self.auth, 
            verify=self.verify,
            timeout=self.timeout
        )
        response.raise_for_status()
        return response.json()