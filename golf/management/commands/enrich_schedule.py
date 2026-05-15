import time

import requests
from django.core.management.base import BaseCommand

from golf.models import Course, Tournament


class Command(BaseCommand):
    help = 'Enrich scheduled tournaments with purse and course data from ESPN'

    def handle(self, *args, **options):
        tournaments = Tournament.objects.filter(
            status__in=[Tournament.Status.SCHEDULED, Tournament.Status.IN_PROGRESS]
        ).order_by('start_date')

        self.stdout.write(f'Enriching {tournaments.count()} tournaments...\n')

        for t in tournaments:
            try:
                r = requests.get(
                    f'https://sports.core.api.espn.com/v2/sports/golf/leagues/pga/events/{t.espn_id}',
                    timeout=10,
                )
                r.raise_for_status()
                data = r.json()

                updated = []

                purse = data.get('purse')
                if purse and not t.purse:
                    t.purse = purse
                    updated.append('purse')

                courses = data.get('courses', [])
                if courses and t.course is None:
                    c = courses[0]
                    addr = c.get('address', {})
                    course, _ = Course.objects.update_or_create(
                        name=c['name'],
                        defaults={
                            'city':    addr.get('city', ''),
                            'state':   addr.get('state', ''),
                            'country': addr.get('country', 'USA'),
                            'par':     c.get('shotsToPar'),
                            'yardage': c.get('totalYards'),
                        },
                    )
                    t.course = course
                    updated.append('course')

                if updated:
                    t.save(update_fields=updated + (['course'] if 'course' in updated else []))
                    self.stdout.write(f'  {t.name}: updated {", ".join(updated)}')
                else:
                    self.stdout.write(f'  {t.name}: already complete')

                time.sleep(0.2)

            except Exception as e:
                self.stdout.write(self.style.WARNING(f'  {t.name}: failed ({e})'))

        self.stdout.write(self.style.SUCCESS('\nDone.'))
