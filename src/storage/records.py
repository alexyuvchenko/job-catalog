"""Plain records that the catalog returns."""

from __future__ import annotations

from dataclasses import dataclass, field

from core.models import Job


@dataclass
class MergeStats:
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    deactivated: int = 0


@dataclass
class JobMarks:
    favorite: bool = False
    hidden: bool = False
    rating: int = 0
    viewed_at: str = ""

    @property
    def viewed(self) -> bool:
        return bool(self.viewed_at)


@dataclass
class StoredJob:
    job: Job
    active: bool
    first_seen: str
    last_seen: str
    marks: JobMarks = field(default_factory=JobMarks)
    changed_at: str = ""
    changes: tuple[str, ...] = ()
    closed_at: str = ""
    # What the latest refresh did to this vacancy.
    changed_now: bool = False
    closed_now: bool = False
    language: str = ""

    @property
    def change(self) -> str:
        """The latest refresh's effect on this vacancy: closed, added, changed, or ''."""
        if self.closed_now:
            return "closed"
        if self.job.is_new:
            return "added"
        if self.changed_now:
            return "changed"
        return ""
