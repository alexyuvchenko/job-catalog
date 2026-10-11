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
