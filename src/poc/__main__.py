from __future__ import annotations

import asyncio
from datetime import datetime

from poc.automation import submit_entries
from poc.models import EntryData


def local_today_iso() -> str:
    return datetime.now().astimezone().date().isoformat()


ENTRY = EntryData(
    date_iso=local_today_iso(),
    duration="1h",
    description="test",
    project="Miquido - AI",
    tags=("backend",),
)


def main() -> None:
    asyncio.run(submit_entries([ENTRY]))


if __name__ == "__main__":
    main()
