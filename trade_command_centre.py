"""TradingBot V1 — Trade Command Centre desktop entry point."""
from desktop.main_window import main, run_app

if __name__ == "__main__":
    main()


def run() -> int:
    return run_app()
