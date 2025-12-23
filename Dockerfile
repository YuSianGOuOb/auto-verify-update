# 使用輕量級的 Python 3.11 映像檔
FROM python:3.11-slim

# 設定工作目錄
WORKDIR /app

# 設定環境變數
# PYTHONDONTWRITEBYTECODE: 防止 Python 產生 .pyc 檔案
# PYTHONUNBUFFERED: 強制 stdout/stderr 即時輸出 (看 Log 很重要)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# 安裝系統層級的依賴 (如果需要的話)
# 例如：某些 CPLD 工具可能需要 ipmitool 或 build-essential
RUN apt-get update && apt-get install -y \
    ipmitool \
    sshpass \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 1. 先複製 requirements.txt 並安裝依賴
# (這樣做的好處是：如果只改程式碼沒改依賴，Docker 會用 Cache，加速 build 時間)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 2. 複製剩餘的專案程式碼
COPY . .

# 設定容器啟動時的預設指令
# 假設你的入口是 main.py，並且接受一個設定檔路徑作為參數
CMD ["python", "main.py", "--config", "config/inventory.yaml"]