import logging
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger(__name__)


def scrape_job():
    logger.info('scrape_job fired')
    try:
        from django.core.management import call_command
        call_command('scrape_pga')
        logger.info('scrape_job completed')
    except Exception:
        logger.exception('scrape_job failed')


def backfill_job():
    logger.info('backfill_job fired')
    try:
        from django.core.management import call_command
        call_command('scrape_pga', backfill=8)
        logger.info('backfill_job completed')
    except Exception:
        logger.exception('backfill_job failed')


def start():
    logger.info('Starting scheduler')
    scheduler = BackgroundScheduler()

    scheduler.add_job(
        scrape_job,
        'interval',
        minutes=1,
        id='scrape_pga',
        replace_existing=True,
        next_run_time=datetime.now(),
    )

    scheduler.add_job(
        backfill_job,
        'cron',
        hour=2,
        minute=0,
        id='backfill_pga',
        replace_existing=True,
    )

    scheduler.start()
    logger.info('Scheduler started')
