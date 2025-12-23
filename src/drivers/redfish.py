import requests
import urllib3
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type
import os
import json
import subprocess # [新增] 用於呼叫 curl
import tempfile   # [新增] 用於建立暫存參數檔

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

    # [重寫] 改用 curl 來處理上傳，規避 requests 的 Multipart 相容性問題
    def post_file(self, endpoint, file_path, payload=None, file_key="UpdateFile"):
        url = f"{self.base_url}{endpoint}"
        local_param_file = "parameters.json" # [FIX 1] 強制使用固定檔名
        has_params = False

        
        try:
            # 2. 建構 curl 指令
            # -k: 忽略憑證
            # -s: 靜默模式 (不顯示進度條，但會顯示錯誤)
            # -S: 發生錯誤時顯示錯誤訊息
            # -v: 詳細模式 (如果您需要 debug 詳細 HTTP 互動，可打開)
            cmd = [
                "curl", "-k", "-s", "-S",
                "-u", f"{self.auth[0]}:{self.auth[1]}",
                "-X", "POST", url,
                # 上傳主檔案
                "-F", f"{file_key}=@{file_path}" 
            ]

            # 3. 處理額外參數 (JSON)
            if payload:
                # 尋找是否有需要轉成檔案的參數 (如 UpdateParameters)
                # 這裡假設 payload 結構是 {"UpdateParameters": {...}}
                for key, value in payload.items():
                    if isinstance(value, (dict, list)):
                        # 建立實體的 parameters.json
                        with open(local_param_file, "w") as f:
                            json.dump(value, f)
                        has_params = True
                        
                        # 加入 curl 參數
                        # 注意：這裡檔名就是 parameters.json，完全符合 Postman 行為
                        cmd.extend(["-F", f"{key}=@{local_param_file};type=application/json"])
                    else:
                        cmd.extend(["-F", f"{key}={str(value)}"])

            print(f"[Redfish/Curl] Executing upload to {endpoint}...")
            print(" ".join(cmd)) # Debug 用：印出完整指令 (會包含密碼，小心使用)

            # 4. 執行指令
            # capture_output=True 會抓取 stdout/stderr
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

            if result.returncode != 0:
                print(f"[Redfish/Curl] Stderr: {result.stderr}")
                raise RuntimeError(f"Curl execution failed with code {result.returncode}")

            output = result.stdout.strip()
            if not output:
                return {"Status": "OK", "Message": "No response body"}

            try:
                response_json = json.loads(output)
                
                # [FIX] 新增錯誤檢查邏輯
                # 如果回傳的 JSON 包含 "error" 欄位，這通常代表業務邏輯失敗 (即使 HTTP 200)
                if "error" in response_json:
                    error_obj = response_json["error"]
                    # 印出錯誤細節
                    print(f"[Redfish/Curl] API Logic Error Detected: {json.dumps(error_obj, indent=2)}")
                    
                    # 取出錯誤訊息並拋出異常，讓程式停止
                    msg = error_obj.get("message", "Unknown Error")
                    code = error_obj.get("code", "Unknown Code")
                    raise RuntimeError(f"Redfish API Failed: [{code}] {msg}")

                return response_json
            except json.JSONDecodeError:
                # 檢查是否包含錯誤關鍵字
                if "error" in output.lower() or "invalid" in output.lower():
                     # 這次如果失敗，我們直接把原始回應印出來當錯誤訊息
                     raise RuntimeError(f"Upload failed (Raw Output): {output}")
                return {"Status": "Unknown", "Raw": output}

        except subprocess.TimeoutExpired:
            print("[Redfish/Curl] Upload timed out!")
            raise
        except Exception as e:
            print(f"[Redfish/Curl] Exception: {e}")
            raise
        finally:
            # 5. 清理暫存檔
            if has_params and os.path.exists(local_param_file):
                os.remove(local_param_file)

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