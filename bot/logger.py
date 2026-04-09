import logging
import os
import sys
from rich.logging import RichHandler
from rich.console import Console

console = Console()

def _is_server_mode() -> bool:
    """Detect if running inside the FastAPI server (no colour output wanted)."""
    for flag in ("BOT_SERVER_MODE", "BOT_NON_INTERACTIVE"):
        if os.getenv(flag, "").strip().lower() in {"1", "true", "yes", "on"}:
            return True
    # Respect NO_COLOR convention (https://no-color.org/)
    if os.getenv("NO_COLOR", "").strip():
        return True
    return False


def setup_logger(debug: bool = False) -> logging.Logger:
    """Setup structured logging.

    In server mode (BOT_SERVER_MODE=1) we use a plain StreamHandler to stdout
    so that log lines arrive at the SSE client without ANSI escape codes or
    Rich markup tags that would corrupt the terminal UI.

    In interactive/local mode we use RichHandler for pretty output.
    """
    level = logging.DEBUG if debug else logging.INFO

    if _is_server_mode():
        # Plain formatter — no colour, no markup, no boxes.
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter(
                fmt="%(levelname)s  %(message)s",
                datefmt=None,
            )
        )
        logging.basicConfig(level=level, handlers=[handler], force=True)
    else:
        logging.basicConfig(
            level=level,
            format="%(message)s",
            datefmt="[%X]",
            handlers=[RichHandler(rich_tracebacks=True, console=console, show_path=debug)],
        )
    return logging.getLogger("bot")


logger = setup_logger()


def print_summary(summary):
    if _is_server_mode():
        # Plain output — no ANSI / Rich markup that would corrupt the SSE stream.
        print()
        print("================ SUMMARY ================")
        print(f"Subjects processed: {summary.total_subjects_found}")
        print(f"Pending found:      {summary.total_pending_found}")
        print(f"Submitted:          {summary.total_submitted}")
        print(f"Skipped:            {summary.total_skipped}")
        print(f"Failed:             {summary.total_failed}")
        print("=========================================")
        print()
    else:
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
