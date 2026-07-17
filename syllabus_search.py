"""Search helpers for the 2026 syllabus data."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import unicodedata


ROOT = Path(__file__).resolve().parent
DEFAULT_DATA_PATH = ROOT / "data" / "syllabus.json"
DEFAULT_SYLLABUS_YEAR = "2026"


def record_year(record: dict[str, str]) -> str:
    return str(record.get("年度") or DEFAULT_SYLLABUS_YEAR)


def normalize_search_text(value: str) -> str:
    """Normalize spelling variants used when searching course titles."""
    value = unicodedata.normalize("NFKC", str(value)).casefold()
    # Apply longer variants first so every common abbreviation reaches the
    # canonical wording used by the syllabus.
    value = value.replace("微積分学", "微分積分学")
    value = value.replace("微積分", "微分積分")
    value = value.replace("微積", "微分積分")
    return re.sub(r"[\s　・･,，、:：()（）\[\]［］]+", "", value)


@dataclass(frozen=True)
class SearchHit:
    score: tuple[int, int, str]
    record: dict[str, str]


class SyllabusSearchEngine:
    def __init__(self, records: list[dict[str, str]]):
        self.records = records
        self._indexed = [
            (
                record,
                normalize_search_text(record.get("授業科目名", "")),
                normalize_search_text(record.get("前身科目", "")),
            )
            for record in records
        ]
        self.years = sorted({record_year(record) for record in records}, reverse=True)

    @classmethod
    def from_json(cls, path: Path = DEFAULT_DATA_PATH) -> "SyllabusSearchEngine":
        return cls(json.loads(path.read_text(encoding="utf-8")))

    def search(
        self,
        query: str,
        limit: int | None = None,
        year: str | None = None,
    ) -> list[dict[str, str]]:
        normalized = normalize_search_text(query)
        if not normalized:
            return []

        hits = []
        for record, title, predecessor in self._indexed:
            if year and record_year(record) != str(year):
                continue
            match_target = title if normalized in title else predecessor
            if not match_target or normalized not in match_target:
                continue
            if title == normalized:
                rank = 0
            elif title.startswith(normalized):
                rank = 1
            elif normalized in title:
                rank = 2
            else:
                rank = 3  # Hit through the predecessor title.
            hits.append(SearchHit((rank, len(title), title), record))

        hits.sort(key=lambda hit: hit.score)
        records = [hit.record for hit in hits]
        return records[:limit] if limit is not None else records

    def suggestions(self, query: str, limit: int = 8, year: str | None = None) -> list[str]:
        seen = set()
        suggestions = []
        for record in self.search(query, year=year):
            title = record.get("授業科目名", "")
            if not title or title in seen:
                continue
            seen.add(title)
            suggestions.append(title)
            if len(suggestions) >= limit:
                break
        return suggestions
