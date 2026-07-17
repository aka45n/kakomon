#!/usr/bin/env python3
"""Extract engineering syllabus PDFs for 2024 and 2025 and build all-year data."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from import_syllabus_2026 import SOURCES, extract, strip_section_codes


YEARS = ("2024", "2025")
SOURCE_DEPARTMENTS = (
    "建築学科",
    "電気電子工学科",
    "理工化学科",
    "地球工学科",
    "情報学科",
    "物理工学科",
)
COMMON_COURSES = {
    "工学倫理",
    "工学序論",
    "工学部国際インターンシップ１",
    "工学部国際インターンシップ２",
}
COMMON_COURSE_PREFIXES = (
    "グローバル・リーダーシップセミナー I ",
    "グローバル・リーダーシップセミナー II ",
)
CID_REPLACEMENTS = {
    "(cid:8443)": "﨑",
}
FIELDS = (
    "授業科目名",
    "担当者名",
    "配当学年",
    "開講期",
    "曜時限",
    "群",
    "学科",
    "前身科目",
    "年度",
)


def source_names(year: str) -> tuple[str, ...]:
    return tuple(name.replace("2026", year) for name in SOURCES)


def normalize_record(
    record: dict[str, str],
    year: str,
    *,
    blank_predecessor: bool = True,
    department: str | None = None,
) -> dict[str, str]:
    record = dict(record)
    for field, value in record.items():
        for source, replacement in CID_REPLACEMENTS.items():
            value = str(value).replace(source, replacement)
        record[field] = value
    record["授業科目名"] = strip_section_codes(record.get("授業科目名", ""))
    if blank_predecessor:
        record["前身科目"] = ""
    if department is not None:
        course = record["授業科目名"]
        is_common = course in COMMON_COURSES or course.startswith(COMMON_COURSE_PREFIXES)
        record["学科"] = "" if is_common else department
    record["年度"] = year
    return {field: str(record.get(field, "")) for field in FIELDS}


def write_records(path_stem: Path, records: list[dict[str, str]]) -> None:
    path_stem.with_suffix(".json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    with path_stem.with_suffix(".csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(records)


def main() -> None:
    downloads = Path.home() / "Downloads"
    output_dir = Path("data")

    year_records: dict[str, list[dict[str, str]]] = {}
    for year in YEARS:
        records: list[dict[str, str]] = []
        for filename, department in zip(source_names(year), SOURCE_DEPARTMENTS, strict=True):
            pdf_path = downloads / filename
            if not pdf_path.exists():
                raise FileNotFoundError(pdf_path)
            extracted = extract(pdf_path)
            records.extend(
                normalize_record(record, year, department=department)
                for record in extracted
            )
            print(f"  {year} {department}: {len(extracted)} records", flush=True)
        year_records[year] = records
        write_records(output_dir / f"syllabus_{year}", records)
        print(f"wrote {len(records)} records for {year}", flush=True)

    records_2026 = json.loads((output_dir / "syllabus_2026.json").read_text(encoding="utf-8"))
    all_records = [
        normalize_record(record, "2026", blank_predecessor=False)
        for record in records_2026
    ]
    all_records.extend(year_records["2025"])
    all_records.extend(year_records["2024"])
    write_records(output_dir / "syllabus", all_records)
    print(f"wrote {len(all_records)} records to all-year data", flush=True)


if __name__ == "__main__":
    main()
