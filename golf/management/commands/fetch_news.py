import requests
from django.core.management.base import BaseCommand
from django.utils.dateparse import parse_datetime
from django.utils import timezone

from golf.models import NewsArticle


ESPN_URL = "https://site.api.espn.com/apis/site/v2/sports/golf/pga/news"
SOURCE = "ESPN"
ARCHIVE_THRESHOLD = 10


class Command(BaseCommand):
    help = "Fetch PGA Tour news from the ESPN headline API and upsert into the database."

    def handle(self, *args, **options):
        self.stdout.write("Fetching PGA Tour news from ESPN API...")

        try:
            response = requests.get(ESPN_URL, timeout=(5, 15))
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as exc:
            self.stderr.write(f"Request failed: {exc}")
            return
        except ValueError as exc:
            self.stderr.write(f"JSON decode error: {exc}")
            return

        articles = data.get("articles", [])
        if not articles:
            self.stdout.write("No articles returned from API.")
            return

        created_count = 0
        updated_count = 0

        for item in articles:
            # --- Extract fields ---
            title = item.get("headline", "").strip()
            summary = item.get("description", "").strip()

            # article URL — prefer web link, fall back to mobile
            links = item.get("links", {})
            web_links = links.get("web", {})
            article_url = web_links.get("href", "").strip()
            if not article_url:
                article_url = links.get("mobile", {}).get("href", "").strip()
            if not article_url:
                self.stdout.write(f"Skipping article with no URL: {title[:60]}")
                continue

            # image URL — first image in the list
            image_url = ""
            images = item.get("images", [])
            if images:
                image_url = images[0].get("url", "").strip()

            # published date
            published_str = item.get("published", "") or item.get("lastModified", "")
            published_at = None
            if published_str:
                published_at = parse_datetime(published_str)
                if published_at and timezone.is_naive(published_at):
                    published_at = timezone.make_aware(published_at)

            # --- Upsert ---
            obj, created = NewsArticle.objects.update_or_create(
                article_url=article_url,
                defaults={
                    "title": title,
                    "summary": summary,
                    "image_url": image_url,
                    "source": SOURCE,
                    "published_at": published_at,
                    "archived": False,
                },
            )

            if created:
                created_count += 1
            else:
                updated_count += 1

        self.stdout.write(f"Created: {created_count}  Updated: {updated_count}")

        # --- Auto-archive: keep only the 10 newest per source active ---
        active_ids = list(
            NewsArticle.objects
            .filter(source=SOURCE, archived=False)
            .order_by("-published_at")
            .values_list("id", flat=True)
        )

        if len(active_ids) > ARCHIVE_THRESHOLD:
            ids_to_archive = active_ids[ARCHIVE_THRESHOLD:]
            archived_count = NewsArticle.objects.filter(id__in=ids_to_archive).update(archived=True)
            self.stdout.write(f"Auto-archived {archived_count} older articles from {SOURCE}.")

        self.stdout.write(self.style.SUCCESS("fetch_news completed successfully."))
