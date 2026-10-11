"""Request fields for one person's notes on a vacancy."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from storage.filters import MAX_RATING


class MarksUpdate(BaseModel):
    """A change to your own notes about one vacancy. Omitted fields stay as they are."""

    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=1, max_length=2000)
    favorite: bool | None = None
    hidden: bool | None = None
    rating: int | None = Field(default=None, ge=0, le=MAX_RATING)
    viewed: bool | None = None
