"""
Entry point for the Wind Turbine Internal Corrosion Detection System.

Initializes the Application, parses command-line arguments, and handles
system signals for graceful shutdown.
"""

import argparse
import signal as os_signal
import sys
import traceback
from pathlib import Path

from src.core.app import App


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Wind Turbine Internal Corrosion Detection System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py
  python main.py --config-dir ./my_config
  python main.py --log-level DEBUG
        """,
    )

    parser.add_argument(
        "--config-dir",
        type=str,
        default="config",
        help="Path to configuration directory (default: config)",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Override logging level (default: INFO)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="Wind Turbine Corrosion Detection System v1.0.0",
    )

    return parser.parse_args()


def setup_signal_handlers(app: App) -> None:
    """Register OS signal handlers for graceful shutdown."""

    def handle_shutdown(signum: int, frame: object) -> None:
        print(f"\nReceived signal {signum}, shutting down...")
        app.stop()
        sys.exit(0)

    signals_to_handle = []
    if hasattr(os_signal, "SIGINT"):
        signals_to_handle.append(os_signal.SIGINT)
    if hasattr(os_signal, "SIGTERM"):
        signals_to_handle.append(os_signal.SIGTERM)

    for sig in signals_to_handle:
        try:
            os_signal.signal(sig, handle_shutdown)
        except (ValueError, OSError):
            pass


def main() -> int:
    """Application entry point.

    Returns:
        Exit code (0 for success, non-zero for failure).
    """
    args = parse_args()

    app = App(config_dir=args.config_dir)

    if not app.initialize():
        print("CRITICAL: Failed to initialize the application.", file=sys.stderr)
        return 1

    if args.log_level:
        logger = app.logger
        if logger:
            logger.set_level(args.log_level)
            logger.get_logger("main").info(f"Log level override: {args.log_level}")

    setup_signal_handlers(app)

    if not app.start():
        print("CRITICAL: Failed to start the application.", file=sys.stderr)
        return 2

    try:
        log = app.logger.get_logger("main") if app.logger else None
        if log:
            log.info("Application running. Press Ctrl+C to stop.")
            log.info("Watchdog and periodic diagnostics are active.")

        app.run()

    except KeyboardInterrupt:
        pass
    except Exception:
        traceback.print_exc()
    finally:
        app.stop()

    return 0


if __name__ == "__main__":
    sys.exit(main())
