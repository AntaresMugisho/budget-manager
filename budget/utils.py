"""Mise en forme des montants, des dates et des mois, à la française."""

import datetime as dt
from decimal import Decimal

MONTHS_FR = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]
MONTHS_SHORT_FR = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
SYMBOLS = {"CDF": "FC", "USD": "$"}


def number(value, decimals=2):
    """1234567.5 → '1 234 567,50' (espace insécable fine comme séparateur de milliers)."""
    value = Decimal(value or 0)
    text = f"{abs(value):,.{decimals}f}".replace(",", " ").replace(".", ",")
    return f"-{text}" if value < 0 else text


def money(value, currency="CDF", decimals=None):
    if decimals is None:
        decimals = 0 if currency == "CDF" else 2
    return f"{number(value, decimals)} {SYMBOLS.get(currency, currency)}"


def first_of_month(day=None):
    day = day or dt.date.today()
    return day.replace(day=1)


def add_months(day, months):
    index = day.year * 12 + day.month - 1 + months
    return dt.date(index // 12, index % 12 + 1, 1)


def month_label(day, short=False):
    names = MONTHS_SHORT_FR if short else MONTHS_FR
    label = f"{names[day.month - 1]} {day.year}"
    return label if short else label.capitalize()


def date_fr(day):
    if not day:
        return ""
    return f"{day.day:02d}/{day.month:02d}/{day.year}"


def parse_month(value):
    """'2026-11' → date(2026, 11, 1) ; None si la valeur est invalide."""
    try:
        year, month = (int(part) for part in str(value).split("-")[:2])
        return dt.date(year, month, 1)
    except (TypeError, ValueError):
        return None


def percent(part, total):
    total = Decimal(total or 0)
    if total == 0:
        return 0
    return round(float(Decimal(part or 0) / total * 100), 1)
