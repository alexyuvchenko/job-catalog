from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class Job:
    source: str
    job_id: str
    title: str
    company: str
    company_url: str
    url: str
    location: str
    remote: str
    salary_min: int | None
    salary_max: int | None
    currency: str | None
    salary_text: str
    category: str
    english: str
    years: float | None
    published: str
    reservation: str
    evidence: str
    snippet: str
    is_new: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Listing:
    """Jobs read from one board, and whether that read covered the whole listing."""

    jobs: list[Job]
    message: str
    complete: bool = True


@dataclass
class SourceStatus:
    name: str
    ok: bool
    message: str
    fetched: int = 0
    kept: int = 0
    complete: bool = True


@dataclass
class CompanyReview:
    """DOU's published company score and the pages it comes from.

    ``rating`` is the employee survey out of 100. Written reviews have no
    numeric mark of their own, so they are linked instead of rescored.
    """

    rating: int | None
    review_count: int
    voter_count: int
    reviews_url: str
    poll_url: str
    profile_url: str
