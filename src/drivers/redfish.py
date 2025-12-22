import requests
import urllib3
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type
import os

# 忽略自簽憑證警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class RedfishClient:
    def __init__(self, ip, user, password):
        self.base_url = f"https://{ip}"
        self.auth = (user, password)
        self.verify = False
        self.timeout = 30

    # [FIX] 加上 retry=
    @retry(stop=stop_after_attempt(3), wait=wait_fixed(2), retry=retry_if_exception_type(requests.RequestException))
    def get(self, endpoint):
        """通用 GET 請求"""
        url = f"{self.base_url}{endpoint}"
        response = requests.get(url, auth=self.auth, verify=self.verify, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    # [FIX] 加上 retry=
    @retry(stop=stop_after_attempt(3), wait=wait_fixed(2), retry=retry_if_exception_type(requests.RequestException))
    def post_file(self, endpoint, file_path, payload=None, file_key="UpdateFile"):
        """
        上傳韌體檔案
        :param payload: 額外的 JSON 參數 (如 Targets)
        """
        url = f"{self.base_url}{endpoint}"
        filename = os.path.basename(file_path)
        
        # 組合 Multipart/Form-Data
        try:
            with open(file_path, 'rb') as f:
                files = {
                    file_key: (filename, f, 'application/octet-stream')
                }
                data = payload if payload else {}

                print(f"[Redfish] Uploading {filename} to {endpoint}...")
                response = requests.post(
                    url, 
                    files=files, 
                    data=data, 
                    auth=self.auth, 
                    verify=self.verify,
                    timeout=300
                )
                response.raise_for_status()
                return response.json()
                
        except FileNotFoundError:
            raise FileNotFoundError(f"Firmware file not found: {file_path}")
        except requests.RequestException as e:
            print(f"[Redfish] Upload failed: {e}")
            raise

    def post_action(self, endpoint, payload):
        """執行 Action (如 Reset)"""
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