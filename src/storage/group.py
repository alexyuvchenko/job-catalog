"""Same title at the same company is one row, with a link for each board."""

from __future__ import annotations

from dataclasses import replace

from core.constants import SOURCE_NAMES
from core.models import Job
from storage.records import JobMarks, StoredJob

_SOURCE_RANK = {name: index for index, name in enumerate(SOURCE_NAMES)}


def position_key(job: Job) -> tuple[str, str] | None:
    """Title and company, folded. Missing either means the vacancy stays on its own."""
    return position_key_parts(job.title, job.company)


def company_key(company: str) -> str:
    """Company name folded the same way a grouped row matches its siblings."""
    return " ".join(company.split()).casefold()


def position_key_parts(title: str, company: str) -> tuple[str, str] | None:
    folded_title = " ".join(title.split()).casefold()
    folded_company = company_key(company)
    if not folded_title or not folded_company:
        return None
    return folded_title, folded_company


def group_same_positions(items: list[StoredJob]) -> list[StoredJob]:
    """Collapse listings of the same role into the first row that already had that order."""
    order: list[tuple[str, str] | int] = []
    buckets: dict[tuple[str, str], list[StoredJob]] = {}
    singles: dict[int, StoredJob] = {}
    for index, item in enumerate(items):
        key = position_key(item.job)
        if key is None:
            order.append(index)
            singles[index] = _with_listings(item, ((item.job.source, item.job.url),))
            continue
        if key not in buckets:
            order.append(key)
            buckets[key] = []
        buckets[key].append(item)
    grouped: list[StoredJob] = []
    for marker in order:
        if isinstance(marker, int):
            grouped.append(singles[marker])
        else:
            grouped.append(_merge_group(buckets[marker]))
    return grouped


def _merge_group(members: list[StoredJob]) -> StoredJob:
    listings = tuple(
        (item.job.source, item.job.url)
        for _, item in sorted(
            enumerate(members),
            key=lambda pair: (_SOURCE_RANK.get(pair[1].job.source, len(_SOURCE_RANK)), pair[0]),
        )
    )
    primary = members[0]
    if len(members) == 1:
        return _with_listings(primary, listings)
    all_new = all(item.job.is_new for item in members)
    any_new = any(item.job.is_new for item in members)
    all_closed = all(not item.active for item in members)
    first_seen = min(
        (item.first_seen for item in members if item.first_seen), default=primary.first_seen
    )
    last_seen = max(
        (item.last_seen for item in members if item.last_seen), default=primary.last_seen
    )
    changed_at = max((item.changed_at for item in members if item.changed_at), default="")
    viewed_at = next((item.marks.viewed_at for item in members if item.marks.viewed_at), "")
    return StoredJob(
        job=replace(primary.job, is_new=all_new),
        active=not all_closed,
        first_seen=first_seen,
        last_seen=last_seen,
        marks=JobMarks(
            favorite=any(item.marks.favorite for item in members),
            hidden=all(item.marks.hidden for item in members),
            rating=max(item.marks.rating for item in members),
            viewed_at=viewed_at,
        ),
        changed_at=changed_at,
        changes=tuple(dict.fromkeys(name for item in members for name in item.changes)),
        closed_at="" if not all_closed else primary.closed_at,
        changed_now=any(item.changed_now for item in members) or (any_new and not all_new),
        closed_now=all_closed and any(item.closed_now for item in members),
        language=primary.language,
        listings=listings,
    )


def _with_listings(item: StoredJob, listings: tuple[tuple[str, str], ...]) -> StoredJob:
    item.listings = listings
    return item
