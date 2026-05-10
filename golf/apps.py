import os

from django.apps import AppConfig


class GolfConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'golf'

    def ready(self):
        if os.environ.get('RUN_MAIN') == 'true':
            from . import scheduler
            scheduler.start()
