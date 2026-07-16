#!/usr/bin/env python3
"""Extract the 2026 Engineering faculty syllabus PDFs into JSON and CSV."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

import pdfplumber


SOURCES = (
    "syllabus_2026（建築）.pdf",
    "syllabus_2026（電気）.pdf",
    "syllabus_2026（理工）.pdf",
    "syllabus_2026（地球_R4～）.pdf",
    "syllabus_2026（情報）.pdf",
    "syllabus_2026（物理）.pdf",
)

TITLE_WORDS = (
    "特任教授|客員教授|名誉教授|教授|特定准教授|准教授|特任講師|特定講師|講師|"
    "特任助教|特定助教|助教|非常勤講師|研究員|特定研究員|専門職|職員"
)
AFFILIATION_WORDS = (
    "研究科|研究所|学研究科|学舎|学部|大学院|センター|機構|本部|大学|高等学校|"
    "病院|企業|財団|協会|機関|室|部門|専攻"
)


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def header_text(text: str) -> str:
    # All requested values live above the first body section.
    return text.split("[授業の概要・目的]", 1)[0]


def course_name(header: str) -> str:
    match = re.search(r"授業科目名\s+(.+?)\s+担当者所属・", header, re.S)
    if not match:
        return ""
    value = match.group(1).split("<英訳>", 1)[0]
    return clean(value)


def field(header: str, pattern: str) -> str:
    match = re.search(pattern, header, re.S)
    return clean(match.group(1)) if match else ""


def instructor_names(header: str) -> list[str]:
    before_year = header.split("配当学年", 1)[0]
    # Remove the left-column course metadata; what remains around the role labels
    # is the instructor list. Each role is followed by a name.
    candidates: list[str] = []
    for match in re.finditer(rf"(?:{TITLE_WORDS})\s+([^\n]+)", before_year):
        value = clean(match.group(1))
        value = re.split(r"\s+(?:授業科目名|担当者所属・|<英訳>|職名・氏名)", value)[0]
        value = re.sub(r"\s+(?:配当学年|単位数).*$", "", value)
        if value and not re.search(AFFILIATION_WORDS, value):
            candidates.append(value)

    # Some entries intentionally omit a title. In those lines, strip a known
    # affiliation prefix and retain the trailing personal name.
    lines = before_year.splitlines()
    for line in lines:
        if re.search(TITLE_WORDS, line) or any(k in line for k in ("科目ナンバリング", "授業科目名", "<英訳>", "担当者所属", "職名・氏名")):
            continue
        value = clean(line)
        match = re.search(rf"(?:{AFFILIATION_WORDS})\s+(.+)$", value)
        if match:
            name = clean(match.group(1))
            if 1 <= len(name.split()) <= 4:
                candidates.append(name)

    result = []
    for name in candidates:
        name = re.sub(r"^(?:客員|非常勤)\s*", "", name).strip()
        if name in {"関係教員", "担当教員", "未定", "調整中", "未指定"}:
            continue
        if name and name not in result:
            result.append(name)
    return result


def departments(block: str) -> str:
    marker = "[主要授業科目（学部・学科名）]"
    if marker not in block:
        return ""
    value = block.rsplit(marker, 1)[1]
    names = re.findall(r"工学部\s*([^\s、,，/／]+?学科)", value)
    return "・".join(dict.fromkeys(names))


def predecessor(course: str) -> str:
    if course == "情報学概論":
        return "数理工学概論"
    if course.startswith("情報AI基礎演習"):
        return "プログラミング入門"
    if (
        course.startswith("情報AI基礎")
        and not course.startswith("情報AI基礎演習")
    ):
        if "（情報学科）" in course:
            return "計算機科学概論"
        return "情報基礎実践"
    return ""


def extract(pdf_path: Path) -> list[dict[str, str]]:
    records = []
    with pdfplumber.open(pdf_path) as pdf:
        texts = [page.extract_text(x_tolerance=2, y_tolerance=3) or "" for page in pdf.pages]
        starts = [i for i, text in enumerate(texts) if "科目ナンバリング" in text and "授業科目名" in text]
        for position, start in enumerate(starts):
            end = starts[position + 1] if position + 1 < len(starts) else len(texts)
            block = "\n".join(texts[start:end])
            header = header_text(texts[start])
            name = course_name(header)
            grade = field(header, r"配当学年\s+(.+?)\s+単位数")
            term = field(header, r"開講年度・開講期\s+\d{4}・(.+?)(?:\n|使用\s*\n?曜時限)")
            period = field(header, r"曜時限\s+(.+?)\s+授業形態")
            teachers = "・".join(instructor_names(header))
            records.append({
                "授業科目名": name,
                "担当者名": teachers,
                "配当学年": grade,
                "開講期": term,
                "曜時限": period,
                "群": "工学部専門科目",
                "学科": departments(block),
            })
    return records


def main() -> None:
    downloads = Path.home() / "Downloads"
    output_dir = Path("data")
    all_records = []
    for filename in SOURCES:
        path = downloads / filename
        if not path.exists():
            raise FileNotFoundError(path)
        all_records.extend(extract(path))

    supplemental_files = (
        "syllabus_2026_humanities.json",
        "syllabus_2026_natural_foreign_language_information.json",
    )
    for supplemental_file in supplemental_files:
        supplemental_path = output_dir / supplemental_file
        if supplemental_path.exists():
            all_records.extend(json.loads(supplemental_path.read_text()))

    for record in all_records:
        record["前身科目"] = predecessor(record["授業科目名"])

    json_path = output_dir / "syllabus_2026.json"
    csv_path = output_dir / "syllabus_2026.csv"
    json_path.write_text(json.dumps(all_records, ensure_ascii=False, indent=2) + "\n")
    with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(all_records[0]))
        writer.writeheader()
        writer.writerows(all_records)
    print(f"wrote {len(all_records)} records to {json_path} and {csv_path}")


if __name__ == "__main__":
    main()
