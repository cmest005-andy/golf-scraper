import logging
import threading
import time

logger = logging.getLogger(__name__)


def scrape_job():
    print('scrape_job fired', flush=True)
    try:
        from django.core.management import call_command
        call_command('scrape_pga')
        print('scrape_job completed', flush=True)
    except Exception:
        logger.exception('scrape_job failed')


def _run_loop():
    while True:
        scrape_job()
        time.sleep(60)


def start():
    print('Starting scheduler', flush=True)
    t = threading.Thread(target=_run_loop, daemon=True)
    t.start()
    print('Scheduler started', flush=True)
