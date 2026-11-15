"""Run: python -m app.worker  — processes queued jobs and runs the missed-dose scan every 10 minutes."""
import threading, time, logging
from redis import Redis
from rq import Worker, Queue
from .config import get_settings
from .jobs import scan_missed_doses

logging.basicConfig(level=logging.INFO)


def scheduler():
    while True:
        try:
            scan_missed_doses()
        except Exception as e:
            logging.getLogger("caresync.worker").error("scan failed: %s", type(e).__name__)
        time.sleep(600)


if __name__ == "__main__":
    conn = Redis.from_url(get_settings().redis_url)
    threading.Thread(target=scheduler, daemon=True).start()
    Worker([Queue("caresync", connection=conn)], connection=conn).work()
