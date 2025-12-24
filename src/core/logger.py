import logging
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.text import Text
from rich.theme import Theme

# 1. 定義主題顏色
custom_theme = Theme({
    "info": "green",
    "warning": "yellow",
    "error": "bold red"
})

# 2. 建立全域 console 實例 (強制啟用顏色，避免在 Docker 中變黑白)
console = Console(force_terminal=True, theme=custom_theme)

def setup_logger(level="INFO"):
    """
    初始化 Logger 設定
    """
    # 設定 root logger 使用 RichHandler
    # RichHandler 會自動處理時間與顏色
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, rich_tracebacks=True, show_path=False)]
    )

    # [關鍵修正] 將 Paramiko 靜音等級調至 CRITICAL
    # 因為 paramiko 會將 Connection Reset 視為 ERROR，設定為 CRITICAL 才能完全隱藏
    logging.getLogger("paramiko").setLevel(logging.CRITICAL)
    
    # 也可以順便把其他吵雜的 library 靜音
    logging.getLogger("urllib3").setLevel(logging.ERROR)

# 3. 包裝 Logging 方法 (讓原本的程式碼可以無痛轉移)
def info(msg):
    # 使用 logging.info，RichHandler 會自動加上漂亮的 [INFO] 標籤
    logging.info(msg, extra={"markup": True})

def warn(msg):
    logging.warning(msg, extra={"markup": True})

def error(msg):
    logging.error(msg, extra={"markup": True})

# 4. 保留您原本好用的特殊格式輸出
def step(n, msg):
    console.print(f"\n[bold cyan]=== STEP {n}: {msg} ===[/bold cyan]\n")

def info_block(text, title="Raw Output", title_color="cyan"):
    """
    顯示多行文字區塊
    """
    # 讓 title 前面有一行標準的 Log 時間戳記
    info(f"{title}:")

    # 內容使用 Panel 包覆
    body = Text(text, style="white", no_wrap=True)
    panel = Panel(
        body,
        title=f"[{title_color}]{title}[/{title_color}]",
        border_style="white",
        expand=False,
    )
    console.print(panel)