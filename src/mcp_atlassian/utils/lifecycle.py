"""Lifecycle management utilities for graceful shutdown and signal handling."""

import logging
import signal
import sys  # Added import for sys
import threading
from typing import Any

logger = logging.getLogger("mcp-atlassian.utils.lifecycle")

# Global shutdown event for signal-safe handling
_shutdown_event = threading.Event()


def setup_signal_handlers() -> None:
    """Set up signal handlers for graceful shutdown.

    Registers handlers for SIGTERM, SIGINT, and SIGPIPE (if available) to ensure
    the application shuts down cleanly when receiving termination signals.

    This is particularly important for Docker containers running with the -i flag,
    which need to properly handle shutdown signals from parent processes.
    """

    def signal_handler(signum: int, frame: Any) -> None:
        """Handle shutdown signals gracefully.

        Uses event-based shutdown to avoid signal safety issues.
        Signal handlers should be minimal and avoid complex operations.
        """
        # Only safe operations in signal handlers - set the shutdown event
        _shutdown_event.set()

    # Register signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    # Handle SIGPIPE which occurs when parent process closes the pipe.
    # SIGPIPE is Unix-specific; do not register on Windows.
    if sys.platform != "win32":
        try:
            signal.signal(signal.SIGPIPE, signal_handler)
            logger.debug("SIGPIPE handler registered")
        except AttributeError:
            # Fallback for systems where SIGPIPE might not be defined even if not Windows
            logger.debug("SIGPIPE not available on this platform")
    else:
        logger.debug(
            "SIGPIPE is not applicable on Windows, skipping handler registration."
        )


def ensure_clean_exit() -> None:
    """Ensure all output streams are flushed before exit.

    This is important for containerized environments where output might be
    buffered and could be lost if not properly flushed before exit.

    Handles cases where streams may already be closed by the parent process,
    particularly on Windows or when run as a child process.
    """
    logger.info("Server stopped, flushing output streams...")

    # Safely flush stdout
    try:
        if hasattr(sys.stdout, "closed") and not sys.stdout.closed:
            sys.stdout.flush()
    except (ValueError, OSError, AttributeError) as e:
        # Stream might be closed or redirected
        logger.debug(f"Could not flush stdout: {e}")

    # Safely flush stderr
    try:
        if hasattr(sys.stderr, "closed") and not sys.stderr.closed:
            sys.stderr.flush()
    except (ValueError, OSError, AttributeError) as e:
        # Stream might be closed or redirected
        logger.debug(f"Could not flush stderr: {e}")

    logger.debug("Output streams flushed, exiting gracefully")
