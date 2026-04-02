import logging
from rich.logging import RichHandler
from rich.console import Console

console = Console()

def setup_logger(debug: bool = False) -> logging.Logger:
    """Setup structured logging via Rich."""
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True, console=console, show_path=debug)]
    )
    return logging.getLogger("bot")

logger = setup_logger()

def print_summary(summary):
    console.print()
    console.print("[bold cyan]================ SUMMARY ================[/bold cyan]")
    console.print(f"Subjects processed: [bold]{summary.total_subjects_found}[/bold]")
    console.print(f"Pending found:      [bold]{summary.total_pending_found}[/bold]")
    console.print(f"Submitted:          [bold green]{summary.total_submitted}[/bold green]")
    console.print(f"Skipped:            [bold yellow]{summary.total_skipped}[/bold yellow]")
    
    if summary.total_failed > 0:
        console.print(f"Failed:             [bold red]{summary.total_failed}[/bold red]")
    else:
        console.print(f"Failed:             [bold]{summary.total_failed}[/bold]")
    console.print("[bold cyan]=========================================[/bold cyan]")
    console.print()
