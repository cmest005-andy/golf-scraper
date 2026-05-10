# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Django web application that scrapes PGA Tour golf tournament data from the ESPN unofficial API and stores it in SQLite.

## Commands

```bash
# Create and activate virtual environment
python -m venv venv && source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run migrations
python manage.py migrate

# Create superuser (for admin panel)
python manage.py createsuperuser

# Start dev server
python manage.py runserver

# Make migrations after model changes
python manage.py makemigrations

# Open Django shell
python manage.py shell

# Run the ESPN scraper (populates all models)
python manage.py scrape_pga
```

## Architecture

```
golf_scraper/          ← Django project package (settings, urls, wsgi)
  settings/
    base.py            ← All shared settings; reads .env via python-decouple
    local.py           ← Development overrides; default DJANGO_SETTINGS_MODULE
golf/                  ← Single Django app with all domain models
  models.py            ← Player, Course, Tournament, TournamentRound, PlayerScore, Leaderboard, Odds
  admin.py             ← All models registered with list_display, search, and filters
  scraper/
    espn.py            ← Raw ESPN API calls (scoreboard, tournament, leaderboard)
```

## Data flow

ESPN API → `golf/scraper/espn.py` (fetch raw JSON) → Django ORM models → SQLite → Admin panel

## Key models

- `Player` — ESPN player ID, name, country, world ranking
- `Tournament` — ESPN event ID, season, course FK, status, purse
- `TournamentRound` — per-round record tied to a tournament
- `PlayerScore` — per-player per-round score (strokes, score-to-par, thru, status)
- `Leaderboard` — aggregate tournament standing per player
- `Odds` — bookmaker odds (win, top-5, top-10, make cut) with timestamp

## Environment

Settings are loaded from `.env` via `python-decouple`. Required keys: `SECRET_KEY`, `ALLOWED_HOSTS`, `ESPN_API_BASE_URL`.
