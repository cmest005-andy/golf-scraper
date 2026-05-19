import logging
import threading
import time

logger = logging.getLogger(__name__)

# How often each job fires (in seconds)
SCRAPE_INTERVAL = 60        # scrape_pga: every minute
FETCH_NEWS_INTERVAL = 3600  # fetch_news: every hour


def scrape_job():
    print('scrape_job fired', flush=True)
    try:
        from django.core.management import call_command
        call_command('scrape_pga')
        print('scrape_job completed', flush=True)
    except Exception:
        logger.exception('scrape_job failed')


def fetch_news_job():
    print('fetch_news_job fired', flush=True)
    try:
        from django.core.management import call_command
        call_command('fetch_news')
        print('fetch_news_job completed', flush=True)
    except Exception:
        logger.exception('fetch_news_job failed')


def _run_scrape_loop():
    while True:
        scrape_job()
        time.sleep(SCRAPE_INTERVAL)


def _run_news_loop():
    # Stagger the first run by 10 seconds so it doesn't fire simultaneously with scrape_job
    time.sleep(10)
    while True:
        fetch_news_job()
        time.sleep(FETCH_NEWS_INTERVAL)


def start():
    print('Starting scheduler', flush=True)

    scrape_thread = threading.Thread(target=_run_scrape_loop, daemon=True, name='scrape-loop')
    scrape_thread.start()

    news_thread = threading.Thread(target=_run_news_loop, daemon=True, name='news-loop')
    news_thread.start()

    print('Scheduler started (scrape every 60s, news every 3600s)', flush=True)
