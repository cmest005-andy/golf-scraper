import os

from django.apps import AppConfig


class FantasyConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'fantasy'

    def ready(self):
        import sys
        is_devserver_child = os.environ.get('RUN_MAIN') == 'true'
        is_gunicorn = 'gunicorn' in sys.modules or bool(sys.argv and 'gunicorn' in sys.argv[0])
        if is_devserver_child or is_gunicorn:
            from . import scheduler
            scheduler.start()
