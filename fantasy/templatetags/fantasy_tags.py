from django import template

register = template.Library()


@register.filter
def dictlookup(d, key):
    result = d.get(key)
    if result is None:
        result = d.get(str(key))
    return result if result is not None else []


@register.filter
def get_odds(d, key):
    return d.get(key) or d.get(str(key)) or ''


@register.filter
def empty_slots(roster_size, filled):
    """Return a range for unfilled roster slots."""
    return range(max(0, roster_size - filled))
