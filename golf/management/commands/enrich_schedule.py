import time

import requests
from django.core.management.base import BaseCommand

from golf.models import Course, CourseHole, Tournament
from golf.scraper.espn import fetch_wikipedia_bio

WIKI_HEADERS = {'User-Agent': 'AndysFantasyGolfApp/1.0'}


def fetch_course_wiki(course_name):
    """Fetch Wikipedia extract for a golf course."""
    def _get(title):
        return requests.get(
            f'https://en.wikipedia.org/api/rest_v1/page/summary/{title.replace(" ", "_")}',
            headers=WIKI_HEADERS,
            timeout=10,
        )

    r = _get(course_name)
    if r.status_code == 404:
        search = requests.get(
            'https://en.wikipedia.org/w/api.php',
            params={'action': 'query', 'list': 'search', 'srsearch': f'{course_name} golf course',
                    'format': 'json', 'srlimit': 1},
            headers=WIKI_HEADERS,
            timeout=10,
        )
        results = search.json().get('query', {}).get('search', [])
        if not results:
            return ''
        r = _get(results[0]['title'])

    if not r.ok:
        return ''
    data = r.json()
    if data.get('type') == 'disambiguation':
        r = _get(f'{course_name} (golf course)')
        if not r.ok:
            return ''
        data = r.json()
    return data.get('extract', '')


class Command(BaseCommand):
    help = 'Enrich scheduled tournaments with purse, course, scorecard, and bio data'

    def handle(self, *args, **options):
        tournaments = Tournament.objects.filter(
            status__in=[Tournament.Status.SCHEDULED, Tournament.Status.IN_PROGRESS]
        ).select_related('course').order_by('start_date')

        self.stdout.write(f'Enriching {tournaments.count()} tournaments...\n')

        for t in tournaments:
            try:
                r = requests.get(
                    f'https://sports.core.api.espn.com/v2/sports/golf/leagues/pga/events/{t.espn_id}',
                    timeout=10,
                )
                r.raise_for_status()
                data = r.json()

                t_updated = []

                purse = data.get('purse')
                if purse and not t.purse:
                    t.purse = purse
                    t_updated.append('purse')

                espn_courses = data.get('courses', [])
                if espn_courses:
                    c = espn_courses[0]
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

                    if t.course is None:
                        t.course = course
                        t_updated.append('course')

                    # Save scorecard holes if not yet stored
                    if not course.holes.exists():
                        hole_rows = []
                        for h in c.get('holes', []):
                            hole_rows.append(CourseHole(
                                course=course,
                                number=h['number'],
                                par=h['shotsToPar'],
                                yardage=h.get('totalYards'),
                            ))
                        if hole_rows:
                            CourseHole.objects.bulk_create(hole_rows, ignore_conflicts=True)
                            self.stdout.write(f'    Saved {len(hole_rows)} holes for {course.name}')

                    # Fetch Wikipedia bio if missing
                    if not course.wiki_bio:
                        self.stdout.write(f'    Fetching Wikipedia bio for {course.name}...')
                        bio = fetch_course_wiki(course.name)
                        if bio:
                            course.wiki_bio = bio
                            course.save(update_fields=['wiki_bio'])
                            self.stdout.write(f'    Got bio ({len(bio)} chars)')
                        else:
                            self.stdout.write(f'    No Wikipedia bio found')
                        time.sleep(0.5)

                if t_updated:
                    t.save(update_fields=t_updated)
                    self.stdout.write(f'  {t.name}: updated {", ".join(t_updated)}')
                else:
                    self.stdout.write(f'  {t.name}: ok')

                time.sleep(0.2)

            except Exception as e:
                self.stdout.write(self.style.WARNING(f'  {t.name}: failed ({e})'))

        self.stdout.write(self.style.SUCCESS('\nDone.'))
