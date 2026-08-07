from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EntryData:
    date_iso: str
    duration: str
    description: str
    project: str
    tags: tuple[str, ...]

    @property
    def tags_display(self) -> str:
        return ", ".join(self.tags)

    @property
    def summary(self) -> str:
        return (
            f"{self.date_iso} | {self.duration} | {self.description} | "
            f"{self.project} | {self.tags_display or '-'}"
        )
