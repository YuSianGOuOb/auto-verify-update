from rich.console import Console
from rich.panel import Panel
from rich.text import Text

# 強制啟動顏色，即使在 docker、非 TTY、redirect 中也會亮色
console = Console(force_terminal=True)

def info(msg):
    console.print(f"[bold green][INFO][/bold green] {msg}")

def warn(msg):
    console.print(f"[bold yellow][WARN][/bold yellow] {msg}")

def error(msg):
    console.print(f"[bold red][ERROR][/bold red] {msg}")

def step(n, msg):
    console.print(f"\n[bold cyan]=== STEP {n}: {msg} ===[/bold cyan]\n")

def info_block(text, title="Raw Output", title_color="cyan"):
    """
    顯示多行文字區塊，前面只有一行 [INFO]，
    Panel 區塊內不加 [INFO] 前綴。
    """
    # Panel title（顯示在框線上面）
    info(f"{title}:")   # ← 這裡有 [INFO]

    # Panel body 文字變白色
    body = Text(text, style="white", no_wrap=True)

    panel = Panel(
        body,
        title=f"[{title_color}]{title}[/{title_color}]",
        border_style="white",
        expand=False,
    )

    # Panel 本身輸出（不用 [INFO]）
    console.print(panel)
