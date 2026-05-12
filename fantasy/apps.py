import os

from django.apps import AppConfig


class FantasyConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'fantasy'

    def ready(self):
        if os.environ.get('RUN_MAIN') == 'true':
            from . import scheduler
            scheduler.start()
