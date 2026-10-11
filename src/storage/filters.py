"""Which vacancies a person sees: the filter form, sorting, and personal-mark rules."""

from __future__ import annotations

from dataclasses import dataclass

from core.classify import accept_remote, english_meets, salary_meets
from storage.records import JobMarks, StoredJob

MINE_CHOICES = ("", "all", "favorites", "unviewed", "viewed", "rated", "hidden")
CHANGE_CHOICES = ("", "added", "changed", "closed")
LANGUAGE_CHOICES = ("", "en", "uk")
MAX_RATING = 5


@dataclass
class CatalogFilters:
    text: str = ""
    source: str = ""
    full_remote_only: bool = False
    min_salary: int | None = None
    english: str = ""
    min_years: float | None = None
    include_inactive: bool = False
    # Personal marks. "" hides jobs marked "not for me"; "all" shows everything.
    mine: str = ""
    min_rating: int | None = None
    # What the latest refresh did: added, changed, or closed vacancies.
    change: str = ""
    # Language of the description: "en" or "uk".
    language: str = ""
    # Column to sort by ("" keeps the default: newest first) and its direction.
    sort: str = ""
    descending: bool | None = None


SORT_COLUMNS = ("date", "job", "company")
SORT_CHOICES = ("", *SORT_COLUMNS)

# casefold() is not Ukrainian alphabetical order: "і" would sort after "я".
_UKRAINIAN_ALPHABET = "абвгґдеєжзиіїйклмнопрстуфхцчшщьюя"
_UKRAINIAN_ORDER = {letter: chr(0x0430 + index) for index, letter in enumerate(_UKRAINIAN_ALPHABET)}


def default_descending(column: str) -> bool:
    """Date starts with the newest vacancy. A name starts at the beginning of the alphabet."""
    return column in ("", "date")


def active_sort(filters: CatalogFilters) -> tuple[str, bool]:
    """The column and direction the list is actually ordered by.

    An empty column means the date. A direction still applies when the column
    was left out, so ``?dir=asc`` orders that default upwards.
    """
    column = filters.sort if filters.sort in SORT_COLUMNS else "date"
    if filters.descending is None:
        return column, default_descending(column)
    return column, filters.descending


def _label_key(value: str) -> str:
    folded = value.casefold()
    return "".join(_UKRAINIAN_ORDER.get(character, character) for character in folded)


def apply_sort(found: list[StoredJob], filters: CatalogFilters) -> None:
    """Order ``found`` in place.

    The rows already arrive newest first, then by salary, then by title. This
    sort is stable, so equal names keep that order. A missing date is neither
    newer nor older, so it stays after vacancies that have one.
    """
    column, descending = active_sort(filters)
    if column == "date":
        found.sort(key=lambda item: item.job.published, reverse=descending)
        if not descending:
            dated = [item for item in found if item.job.published]
            blank = [item for item in found if not item.job.published]
            found[:] = dated + blank
        return
    attribute = "title" if column == "job" else "company"
    found.sort(key=lambda item: _label_key(getattr(item.job, attribute)), reverse=descending)


def is_visible(stored: StoredJob, filters: CatalogFilters) -> bool:
    if not stored.active and not filters.include_inactive and filters.change != "closed":
        return False
    if not _mine_matches(stored.marks, filters.mine):
        return False
    if filters.min_rating is not None and stored.marks.rating < filters.min_rating:
        return False
    if filters.change and stored.change != filters.change:
        return False
    if filters.language and stored.language != filters.language:
        return False
    job = stored.job
    if filters.source and job.source != filters.source:
        return False
    if filters.text:
        blob = " ".join((job.title, job.company, job.location, job.snippet, job.category)).lower()
        if filters.text.lower() not in blob:
            return False
    if not accept_remote(job.remote, filters.full_remote_only):
        return False
    if not salary_meets(job, filters.min_salary):
        return False
    if not english_meets(job.english, filters.english):
        return False
    if filters.min_years is not None and job.years is not None and job.years < filters.min_years:
        return False
    return True


def _mine_matches(marks: JobMarks, choice: str) -> bool:
    if choice == "all":
        return True
    if choice == "hidden":
        return marks.hidden
    if marks.hidden:
        return False
    if choice == "favorites":
        return marks.favorite
    if choice == "unviewed":
        return not marks.viewed
    if choice == "viewed":
        return marks.viewed
    if choice == "rated":
        return marks.rating > 0
    return True
