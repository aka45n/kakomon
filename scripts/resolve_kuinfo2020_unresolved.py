from __future__ import annotations

from pathlib import Path
import json
import re

from import_kuinfo2020 import ROOT_GROUPS, safe_id_part


ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "exams.json"
UNRESOLVED_PATH = ROOT / "data" / "kuinfo2020_unresolved.json"

EXAM_MARKERS = re.compile(
    r"試験|期末|中間|追試|テスト|過去問|小テスト|mondai|kaitou|prob|exam|answer|ans",
    re.IGNORECASE,
)
NON_EXAM_MARKERS = re.compile(
    r"講義|授業|資料|ノート|レジュメ|レジメ|シケプリ|教科書|参考|スライド|プリント|"
    r"レポート|レポート|練習問題|演習問題|ガイダンス|テキスト|lec|textbook|csv_files|eps_files|gp_files",
    re.IGNORECASE,
)
BAD_EXTENSIONS = {
    ".aux",
    ".csv",
    ".eps",
    ".gp",
    ".log",
    ".synctex.gz",
    ".tex",
    ".xls",
    ".xlsx",
}
SUPPORTED_ADDITIONAL_EXTENSIONS = {"", ".pdf のコピー"}
YEAR_FOLDER_RE = re.compile(r"^(20\d{2})(?:年度)?(?:[（(]([^（）()]*)[）)])?$")
MULTI_YEAR_FOLDER_RE = re.compile(r"^(?:20\d{2}[,，、]?)+(?:[（(]([^（）()]*)[）)])?$")
YEAR_RE = re.compile(r"(20\d{2})(?:年度)?")
FILENAME_RE = re.compile(r"^(?P<subject>.+?)[（(](?P<teacher>[^（）()]*)[）)]\s*(?P<year>20\d{2})(?:年度)?(?P<tail>.*)$")
FILENAME_YEAR_BEFORE_RE = re.compile(r"^(?P<subject>.+?)_?(?P<year>20\d{2})(?:年度)?_?(?P<tail>.*)$")
FILENAME_SUBJECT_YEAR_TEACHER_RE = re.compile(r"^(?P<subject>.+?)[_ ](?P<year>20\d{2})(?:年度)?[（(](?P<teacher>[^（）()]*)[）)](?P<tail>.*)$")
FILENAME_SUBJECT_PAREN_YEAR_TEACHER_RE = re.compile(r"^(?P<subject>.+?)[（(](?P<year>20\d{2})\s+(?P<teacher>[^（）()]*)[）)](?P<tail>.*)$")
SHORT_YEAR_RE = re.compile(r"(?<!\d)(?P<year2>\d{2})(?!\d)")
SHORT_YEAR_RANGE_RE = re.compile(r"(?<!\d)\d{2}\s*[-〜~]\s*\d{2}(?!\d)")
REIWA_YEAR_RE = re.compile(r"R(?P<reiwa>\d+)", re.IGNORECASE)
DATE_LIKE_RE = re.compile(r"^20\d{6}")

METADATA_FOLDERS = {
    "1st",
    "2nd",
    "3rd",
    "4th",
    "前期後期あんまり関係なかった",
    "クラス指定",
    "クラス指定以外",
    "1回生配当科目",
    "2回生配当科目",
    "3回生配当科目",
    "4回生配当科目",
    "試験",
    "テスト",
    "過去問",
    "問題",
    "解答",
}


def main() -> None:
    exams = read_json(DATA_PATH)
    unresolved = read_json(UNRESOLVED_PATH)
    by_id = {item["id"] for item in exams}
    remaining = []
    resolved = []

    for item in unresolved:
        exam = resolve_item(item)
        if not exam:
            remaining.append(item)
            continue
        if exam["id"] in by_id:
            continue
        exams.append(exam)
        by_id.add(exam["id"])
        resolved.append(item)

    exams.sort(key=lambda item: (item.get("subject", ""), item.get("year", ""), item.get("teacher", ""), item.get("id", "")))
    remaining.sort(key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True))
    DATA_PATH.write_text(json.dumps(exams, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    UNRESOLVED_PATH.write_text(json.dumps(remaining, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"resolved={len(resolved)} remaining={len(remaining)} total={len(exams)}")


def resolve_item(item: dict) -> dict | None:
    source = item.get("file")
    if not isinstance(source, dict):
        return None

    file_id = source_id(source)
    filename = source.get("name") or filename_from_notes(source.get("notes", "")) or ""
    folder_path = source.get("folderPath") or folder_path_from_notes(source.get("notes", ""))
    if not file_id or not filename or not folder_path:
        return None

    if not is_exam_like(filename, folder_path) and not looks_like_named_exam_file(filename) and not is_problem_folder(folder_path):
        return None
    if is_bad_extension(filename):
        return None

    parts = folder_parts(folder_path)
    group = ROOT_GROUPS.get(parts[0] if parts else "")
    if not group:
        return None

    parsed = parse_from_filename(filename) or parse_from_problem_folder(parts, filename) or parse_from_folder(parts, filename)
    if not parsed:
        return None
    subject = parsed["subject"]
    teacher = parsed["teacher"]
    year = parsed["year"]
    if not subject or not year:
        return None

    subject = clean_subject(subject, teacher)
    notes = [
        "京都大学",
        f"KUInfo2020科目名候補: {subject}",
        f"ファイル名: {filename}",
        f"フォルダ階層: {folder_path}",
        "未解決からフォルダ階層で再判定",
    ]
    return {
        "id": f"kuinfo2020-{file_id}",
        "year": year,
        "teacher": teacher,
        "subject": subject,
        "group": group,
        "testType": "小テスト" if "小テスト" in filename else "定期テスト",
        "sourceSite": "KUInfo2020",
        "localFile": "未保存",
        "driveUrl": source.get("url") or source.get("driveUrl") or f"https://drive.google.com/file/d/{file_id}/view",
        "notes": " / ".join(notes),
    }


def parse_from_filename(filename: str) -> dict | None:
    stem = stem_name(filename)
    if DATE_LIKE_RE.match(stem):
        return None
    match = FILENAME_RE.match(stem)
    if match:
        subject = normalize_spaces(match.group("subject"))
        teacher = clean_teacher(match.group("teacher"))
        year = match.group("year")
        term = term_from_text(match.group("tail")) or term_from_subject(subject)
        return {"subject": subject, "teacher": teacher, "year": year + term}

    match = FILENAME_SUBJECT_YEAR_TEACHER_RE.match(stem) or FILENAME_SUBJECT_PAREN_YEAR_TEACHER_RE.match(stem)
    if match:
        subject = normalize_spaces(match.group("subject")).strip("_-")
        teacher = clean_teacher(match.group("teacher"))
        year = match.group("year")
        term = term_from_text(match.group("tail")) or term_from_subject(subject)
        return {"subject": subject, "teacher": teacher, "year": year + term}

    match = FILENAME_YEAR_BEFORE_RE.match(stem)
    if match and EXAM_MARKERS.search(match.group("tail")):
        subject = normalize_spaces(match.group("subject")).strip("_-")
        year = match.group("year")
        teacher = teacher_from_parens(stem)
        term = term_from_text(match.group("tail")) or term_from_subject(subject)
        return {"subject": subject, "teacher": teacher, "year": year + term}
    return None


def parse_from_folder(parts: list[str], filename: str) -> dict | None:
    stem = stem_name(filename)
    year = ""
    teacher = ""
    year_index = -1
    for index, part in enumerate(parts):
        match = YEAR_FOLDER_RE.match(part)
        if match:
            year = match.group(1)
            teacher = clean_teacher(match.group(2) or "")
            year_index = index
            continue
        multi_match = MULTI_YEAR_FOLDER_RE.match(part)
        if multi_match:
            teacher = clean_teacher(multi_match.group(1) or "")
            year_index = index
    if not year:
        year = year_from_filename(filename)
    if year_index < 0 and not year:
        if DATE_LIKE_RE.match(stem):
            return None
        match = YEAR_RE.search(filename)
        if not match:
            return None
        year = match.group(1)
    term = explicit_term(parts) or term_from_subject(filename)
    subject = course_from_parts(parts, year_index)
    if not teacher:
        teacher = teacher_from_parens(filename) or teacher_from_parens(subject)
    if not subject:
        subject = subject_from_filename_without_year(filename)
    return {"subject": subject, "teacher": teacher, "year": year + term}


def parse_from_problem_folder(parts: list[str], filename: str) -> dict | None:
    if not is_problem_folder(" / ".join(parts)):
        return None
    year, teacher, year_index = year_teacher_from_parts(parts)
    file_year = year_from_filename(filename)
    if file_year:
        year = file_year
    if not year:
        return None
    subject = course_from_parts(parts, year_index)
    if not subject:
        return None
    return {"subject": subject, "teacher": teacher, "year": year + explicit_term(parts)}


def course_from_parts(parts: list[str], year_index: int) -> str:
    upper = year_index if year_index >= 0 else len(parts)
    for part in reversed(parts[1:upper]):
        if is_metadata_part(part):
            continue
        return normalize_spaces(part)
    return ""


def year_teacher_from_parts(parts: list[str]) -> tuple[str, str, int]:
    year = ""
    teacher = ""
    year_index = -1
    for index, part in enumerate(parts):
        match = YEAR_FOLDER_RE.match(part)
        if match:
            year = match.group(1)
            teacher = clean_teacher(match.group(2) or "")
            year_index = index
            continue
        multi_match = MULTI_YEAR_FOLDER_RE.match(part)
        if multi_match:
            teacher = clean_teacher(multi_match.group(1) or "")
            year_index = index
    return year, teacher, year_index


def year_from_filename(filename: str) -> str:
    stem = stem_name(filename)
    if DATE_LIKE_RE.match(stem):
        return ""
    if SHORT_YEAR_RANGE_RE.search(stem):
        return ""
    match = YEAR_RE.search(stem)
    if match:
        return match.group(1)
    match = REIWA_YEAR_RE.search(stem)
    if match:
        return str(2018 + int(match.group("reiwa")))
    match = SHORT_YEAR_RE.search(stem)
    if match and re.search(r"試験|期末|中間|過去問|fall|spring", stem, re.IGNORECASE):
        value = int(match.group("year2"))
        if 0 <= value <= 40:
            return f"20{value:02d}"
    return ""


def is_exam_like(filename: str, folder_path: str) -> bool:
    text = f"{filename} {folder_path}"
    if NON_EXAM_MARKERS.search(text) and not re.search(r"試験|期末|中間|追試|テスト|過去問|小テスト", text):
        return False
    if "練習問題" in folder_path or "演習問題" in folder_path:
        return False
    if EXAM_MARKERS.search(text):
        return True
    return False


def is_problem_folder(folder_path: str) -> bool:
    return bool(re.search(r"(?:^| / )(問題|試験|テスト|過去問|昨年度の問題|解答)(?: / |$)", folder_path))


def looks_like_named_exam_file(filename: str) -> bool:
    stem = stem_name(filename)
    if DATE_LIKE_RE.match(stem):
        return False
    if NON_EXAM_MARKERS.search(stem):
        return False
    return bool(
        FILENAME_RE.match(stem)
        or FILENAME_SUBJECT_YEAR_TEACHER_RE.match(stem)
        or FILENAME_SUBJECT_PAREN_YEAR_TEACHER_RE.match(stem)
    )


def is_bad_extension(filename: str) -> bool:
    lower = filename.lower()
    if lower.endswith(".synctex.gz"):
        return True
    suffix = Path(filename).suffix.lower()
    if suffix in BAD_EXTENSIONS:
        return True
    if suffix or filename.endswith(tuple(SUPPORTED_ADDITIONAL_EXTENSIONS)):
        return False
    return False


def is_metadata_part(part: str) -> bool:
    if part in METADATA_FOLDERS:
        return True
    if part in ("前期", "後期"):
        return True
    if YEAR_FOLDER_RE.match(part):
        return True
    if MULTI_YEAR_FOLDER_RE.match(part):
        return True
    if re.fullmatch(r"第?[0-9０-９一二三四五六七八九十]+回.*", part):
        return True
    if re.search(r"^第?[0-9０-９一二三四五六七八九十]+回|^[A-Za-z]{3}_?\d+", part):
        return True
    return False


def explicit_term(parts: list[str]) -> str:
    if "前期" in parts:
        return "前期"
    if "後期" in parts:
        return "後期"
    return ""


def term_from_text(value: str) -> str:
    if "前期" in value or "前" in value:
        return "前期"
    if "後期" in value or "後" in value:
        return "後期"
    return ""


def term_from_subject(subject: str) -> str:
    normalized = re.sub(r"[（(].*[）)]$", "", subject).strip()
    if normalized.endswith(("A", "Ⅰ", "I")):
        return "前期"
    if normalized.endswith(("B", "Ⅱ", "II")):
        return "後期"
    return ""


def subject_from_filename_without_year(filename: str) -> str:
    stem = stem_name(filename)
    stem = YEAR_RE.sub("", stem)
    stem = re.sub(r"試験|期末|中間|追試|テスト|過去問|小テスト|再現|解答例?|問題", "", stem)
    stem = re.sub(r"[（(][^（）()]*[）)]", "", stem)
    return normalize_spaces(stem.strip("_- "))


def clean_subject(subject: str, teacher: str) -> str:
    subject = normalize_spaces(subject)
    if teacher:
        subject = re.sub(rf"[（(]{re.escape(teacher)}[）)]", "", subject).strip()
    return subject


def teacher_from_parens(value: str) -> str:
    candidates = re.findall(r"[（(]([^（）()]*)[）)]", value)
    for candidate in reversed(candidates):
        teacher = clean_teacher(candidate)
        if teacher:
            return teacher
    return ""


def clean_teacher(value: str) -> str:
    value = normalize_spaces(value or "")
    if not value:
        return ""
    if re.search(r"pass|前期|後期|文法|演習|実習|問題|解答|概要|計算機|数理|共通|自由にフォルダ|[月火水木金]\d|T\d|S\d|~", value):
        return ""
    return value.replace("_", "・")


def source_id(source: dict) -> str:
    if source.get("id"):
        return str(source["id"]).removeprefix("kuinfo2020-")
    url = source.get("url") or source.get("driveUrl") or ""
    match = re.search(r"/file/d/([^/?#]+)", url)
    return match.group(1) if match else ""


def filename_from_notes(notes: str) -> str:
    return note_value(notes, "ファイル名")


def folder_path_from_notes(notes: str) -> str:
    return note_value(notes, "フォルダ階層")


def note_value(notes: str, label: str) -> str:
    prefix = f"{label}: "
    for part in notes.split(" / "):
        if part.startswith(prefix):
            return part.removeprefix(prefix)
    return ""


def folder_parts(folder_path: str) -> list[str]:
    return [part.strip() for part in folder_path.split("/") if part.strip()]


def stem_name(filename: str) -> str:
    name = filename.removesuffix(" のコピー")
    return Path(name).with_suffix("").name.strip()


def normalize_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", str(value).replace("＿", "_")).strip()


def read_json(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
