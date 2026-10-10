"""Standalone scheduler/worker process: ``python -m app.worker``."""

import logging
import signal
import threading

from app.core.logging import configure_logging
from app.services.jobs import worker_loop


def main() -> None:
    configure_logging()
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    logging.getLogger("datasentry.worker").info("worker starting")
    worker_loop(stop)


if __name__ == "__main__":
    main()
