import logging
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.text import Text
from rich.theme import Theme
from rich.align import Align # [新增] 用於文字置中

# 1. 定義主題顏色
custom_theme = Theme({
    "info": "green",
    "warning": "yellow",
    "error": "bold red"
})

# 2. 建立全域 console 實例 (強制啟用顏色)
console = Console(force_terminal=True, theme=custom_theme)

def setup_logger(level="INFO"):
    """
    初始化 Logger 設定
    """
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, rich_tracebacks=True, show_path=False)]
    )

    # 將 Paramiko 與 urllib3 靜音
    logging.getLogger("paramiko").setLevel(logging.CRITICAL)
    logging.getLogger("urllib3").setLevel(logging.ERROR)

# 3. 包裝 Logging 方法
def info(msg):
    logging.info(msg, extra={"markup": True})

def warn(msg):
    logging.warning(msg, extra={"markup": True})

def error(msg):
    logging.error(msg, extra={"markup": True})

# 4. 特殊格式輸出
def step(n, msg):
    console.print(f"\n[bold cyan]=== STEP {n}: {msg} ===[/bold cyan]\n")

def info_block(text, title="Raw Output", title_color="cyan"):
    """顯示多行文字區塊"""
    info(f"{title}:")
    body = Text(text, style="white", no_wrap=True)
    panel = Panel(
        body,
        title=f"[{title_color}]{title}[/{title_color}]",
        border_style="white",
        expand=False,
    )
    console.print(panel)

def section(msg):
    """
    [新增] 顯示顯眼的段落標題，用於切換元件時
    """
    console.print() # 先空一行
    panel = Panel(
        Align.center(f"[bold white]{msg}[/bold white]", vertical="middle"),
        border_style="bright_magenta",
        padding=(1, 2), # 上下留白 1 行，左右 2 字元
        title="[bold yellow]NEXT TARGET[/bold yellow]",
        subtitle="[dim]Auto-Verify-Update[/dim]"
    )
    console.print(panel)
    console.print()