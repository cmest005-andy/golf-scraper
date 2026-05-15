import os

from django.apps import AppConfig


class GolfConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'golf'

    def ready(self):
        import sys
        is_devserver_child = os.environ.get('RUN_MAIN') == 'true'
        is_gunicorn = bool(sys.argv and 'gunicorn' in sys.argv[0])
        if is_devserver_child or is_gunicorn:
            from . import scheduler
            scheduler.start()
