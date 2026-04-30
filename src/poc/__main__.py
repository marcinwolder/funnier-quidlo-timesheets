from __future__ import annotations

import asyncio
from datetime import date

from poc.automation import submit_entries
from poc.models import EntryData

ENTRY = EntryData(
    date_iso=date.today().isoformat(),
    duration="1h",
    description="test",
    project="Miquido - AI",
    tags=("backend",),
)


def main() -> None:
    asyncio.run(submit_entries([ENTRY]))


if __name__ == "__main__":
    main()
