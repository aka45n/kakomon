from __future__ import annotations

from pathlib import Path
from subprocess import CalledProcessError, TimeoutExpired, run
from urllib.parse import quote
import argparse
import html
import json
import re
import time


ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "exams.json"
REPORT_PATH = ROOT / "data" / "kuwiki_unresolved.json"
KUWIKI_API = "https://www.kuwiki.net/api/exams?q="
USER_AGENT = "Mozilla/5.0 (compatible; kakomon-kuwiki-importer/1.0)"
FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"
SUPPORTED_EXTENSIONS = (
    ".pdf",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".tif",
    ".tiff",
    ".txt",
    ".doc",
    ".docx",
    ".rtf",
    ".html",
    ".pptx",
)
MATERIAL_PATTERNS = (
    "講義ノート",
    "講義資料",
    "授業資料",
    "配布資料",
    "資料",
    "ノート",
    "レジュメ",
    "レジメ",
    "プリント",
    "語彙",
    "単語",
    "スライド",
    "スライド",
    "シケプリ",
    "シケプリ",
    "演習問題",
    "練習問題",
    "補足",
    "論述問題一覧",
    "問題一覧",
    "PyMol実習",
    "講義で用いた図",
    "講義で用いた図",
)
MATERIAL_FILENAME_PATTERNS = (
    r"^append\d*\.pdf$",
    r"^chap\d+\.pdf$",
    r"^nmode\.pdf$",
    r"^STDC",
    r"^chemmeth\d+\.pdf$",
)
REPORT_PATTERNS = (
    "レポート",
    "レポート",
    "ﾚﾎﾟｰﾄ",
    "report",
)
IGNORE_FILENAME_PREFIXES = (
    "中国語の世界",
)
FRONT_TERM_SUFFIXES = ("A", "１", "1", "Ⅰ", "I")
BACK_TERM_SUFFIXES = ("B", "２", "2", "Ⅱ", "II")
NO_YEAR_TRAILING_MARKERS = (
    "",
    "前期",
    "後期",
    "年度不明",
    "不明",
    "unknown",
    "A",
    "B",
    "１",
    "２",
    "1",
    "2",
    "Ⅰ",
    "Ⅱ",
    "I",
    "II",
    "a",
    "b",
)
NO_YEAR_EXCLUDED_PATTERNS = (
    "解答",
    "解説",
    "レポート",
    "レポート",
    "期末",
    "中間",
    "小テスト",
    "再試",
    "追試",
    "演習",
    "練習問題",
    "スライド",
    "スライド",
)
ANSWER_PATTERNS = (
    "解答",
    "解説",
    "答案",
    "略解",
    "答",
    "answer",
)
NON_EXAM_TYPED_PATTERNS = (
    "課題",
    "対策",
)
SMALL_TEST_MARKERS = (
    "小テスト",
    "確認テスト",
    "中テスト",
    "中間",
)
REGULAR_TEST_MARKERS = (
    "期末",
    "定期試験",
    "追試験",
    "試験問題",
    "試験",
)

DEFAULT_TERMS = (
    "数学",
    "物理",
    "化学",
    "生物",
    "地球",
    "情報",
    "英語",
    "語",
    "法",
    "経済",
    "心理",
    "哲学",
    "歴史",
    "文学",
    "教育",
    "統計",
    "解析",
    "代数",
    "幾何",
    "微分",
    "積分",
    "力学",
    "電磁",
    "量子",
    "熱",
    "有機",
    "無機",
    "分析",
    "環境",
    "計算",
    "データ",
    "プログラミング",
    "ドイツ",
    "フランス",
    "中国",
    "スペイン",
    "ロシア",
    "イタリア",
    "朝鮮",
    "日本",
    "アジア",
    "社会",
    "政治",
    "憲法",
    "民法",
    "行政",
    "経営",
    "会計",
    "金融",
    "倫理",
    "宗教",
    "芸術",
    "音楽",
    "健康",
    "スポーツ",
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Import Kyoto University exams from 京大wiki.")
    parser.add_argument("terms", nargs="*", help="京大wiki search terms. Defaults to a broad seed list.")
    parser.add_argument("--limit-courses", type=int, default=0, help="Stop after importing this many course folders.")
    parser.add_argument("--sleep", type=float, default=0.15, help="Delay between Drive folder requests.")
    args = parser.parse_args()

    courses = fetch_courses(args.terms or DEFAULT_TERMS)
    if args.limit_courses:
        courses = courses[: args.limit_courses]

    existing = discard_kuwiki_records(read_json(DATA_PATH, []))
    by_id = {exam["id"]: exam for exam in existing}
    unresolved = []
    imported = 0

    for index, course in enumerate(courses, start=1):
        try:
            files, unsupported_files, empty_folders = fetch_drive_files(course["drive_link"])
        except RuntimeError as error:
            unresolved.append({"course": report_course(course), "reason": str(error)})
            continue
        if not files:
            continue

        for file_item in files:
            if is_ignored_file(file_item["name"]):
                continue
            parsed_items = parse_exam_filename(file_item["name"], course["name"])
            if not parsed_items:
                unresolved.append(
                    {
                        "course": report_course(course),
                        "file": file_item,
                        "reason": "ファイル名から年度または教師名を判定できませんでした。",
                    }
                )
                continue

            if isinstance(parsed_items, dict):
                parsed_items = [parsed_items]
            for parsed in parsed_items:
                exam = build_exam(course, file_item, parsed)
                if exam["id"] not in by_id:
                    existing.append(exam)
                    by_id[exam["id"]] = exam
                    imported += 1

        if index < len(courses):
            time.sleep(args.sleep)

    existing.sort(key=lambda item: (item.get("subject", ""), item.get("year", ""), item.get("teacher", ""), item.get("id", "")))
    DATA_PATH.write_text(json.dumps(existing, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_PATH.write_text(json.dumps(unresolved, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"courses={len(courses)} imported={imported} total={len(existing)} unresolved={len(unresolved)}")


def fetch_courses(terms: tuple[str, ...] | list[str]) -> list[dict]:
    courses_by_drive_id = {}
    for term in terms:
        data = curl_json(KUWIKI_API + quote(term))
        for course in data:
            drive_id = course.get("drive_id")
            if drive_id and drive_id not in courses_by_drive_id:
                courses_by_drive_id[drive_id] = course
    return sorted(courses_by_drive_id.values(), key=lambda item: (item.get("field", ""), item.get("name", "")))


def report_course(course: dict) -> dict:
    return {
        "name": course.get("name") or "未登録",
        "field": course.get("field") or "未登録",
        "code": course.get("code") or "未登録",
    }


def fetch_drive_files(
    folder_url: str,
    visited: set[str] | None = None,
    folder_path: tuple[str, ...] = (),
) -> tuple[list[dict], list[dict], list[dict]]:
    visited = visited or set()
    if folder_url in visited:
        return [], [], []
    visited.add(folder_url)

    page = curl_text(folder_url)
    file_markers = list(
        re.finditer(
            r'\[\[null,"(?P<id>[A-Za-z0-9_-]+)"\],null,null,null,"(?P<mime>[^"]+)"',
            page,
        )
    )
    files = []
    unsupported_files = []
    empty_folders = []
    nested_file_count = 0
    for index, marker in enumerate(file_markers):
        next_start = file_markers[index + 1].start() if index + 1 < len(file_markers) else len(page)
        chunk = page[marker.end() : next_start]
        name_match = re.search(r'\[\[\["([^"]+)"', chunk)
        if not name_match:
            continue
        name = html.unescape(name_match.group(1))
        file_id = marker.group("id")
        mime_type = marker.group("mime")

        if mime_type == FOLDER_MIME_TYPE:
            child_url = f"https://drive.google.com/drive/folders/{file_id}"
            child_path = folder_path + (name,)
            child_files, child_unsupported, child_empty = fetch_drive_files(child_url, visited, child_path)
            files.extend(child_files)
            unsupported_files.extend(child_unsupported)
            empty_folders.extend(child_empty)
            nested_file_count += len(child_files) + len(child_unsupported)
            if not child_files and not child_unsupported and not child_empty:
                empty_folders.append(build_drive_folder(file_id, name, child_path))
            continue

        file_item = build_drive_file(file_id, name, folder_path)
        if Path(name).suffix.lower() in SUPPORTED_EXTENSIONS:
            files.append(file_item)
        else:
            unsupported_files.append(file_item)

    if not folder_path and not files and not unsupported_files and not empty_folders and nested_file_count == 0:
        empty_folders.append({"name": "ルートフォルダ", "folderPath": "ルート"})

    return unique_files(files), unique_files(unsupported_files), unique_folders(empty_folders)


def build_drive_file(file_id: str, name: str, folder_path: tuple[str, ...] = ()) -> dict:
    extension = Path(name).suffix.lower() or "拡張子なし"
    file_item = {
        "id": file_id,
        "name": name,
        "extension": extension,
        "url": f"https://drive.google.com/file/d/{file_id}/view",
    }
    if folder_path:
        file_item["folderPath"] = " / ".join(folder_path)
    return file_item


def build_drive_folder(folder_id: str, name: str, folder_path: tuple[str, ...]) -> dict:
    return {
        "id": folder_id,
        "name": name or "未登録",
        "folderPath": " / ".join(folder_path),
    }


def parse_exam_filename(filename: str, course_name: str) -> dict | None:
    path = Path(filename)
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        return None
    stem = path.with_suffix("").name.strip()
    special = parse_special_filename(stem, course_name)
    if special:
        return special
    year_match = re.search(r"((?:19|20)\d{2})(前期|後期)?$", stem)
    if not year_match:
        return parse_typed_exam_filename(stem, course_name) or parse_no_year_filename(stem, course_name)

    before_year = stem[: year_match.start()].strip()
    teacher = ""
    subject = course_name.strip()

    paren_match = re.search(r"[（(]([^（）()]*)[）)]\s*$", before_year)
    if paren_match:
        teacher = normalize_teacher(paren_match.group(1))
        subject_from_file = before_year[: paren_match.start()].strip()
        if subject_from_file:
            subject = subject_from_file

    year = year_match.group(1) + (year_match.group(2) or infer_term_from_subject(subject))
    return {"year": year, "teacher": teacher, "subject": subject}


def is_material_file(filename: str) -> bool:
    if any(pattern in filename for pattern in MATERIAL_PATTERNS):
        return True
    return any(re.search(pattern, filename, re.IGNORECASE) for pattern in MATERIAL_FILENAME_PATTERNS)


def is_report_file(filename: str) -> bool:
    return any(pattern.lower() in filename.lower() for pattern in REPORT_PATTERNS)


def is_ignored_file(filename: str) -> bool:
    return filename.startswith(IGNORE_FILENAME_PREFIXES) or is_material_file(filename) or is_report_file(filename)


def parse_special_filename(stem: str, course_name: str):
    if stem == "哲学2(戸田)201_":
        return {"year": "", "teacher": "戸田", "subject": "哲学2"}

    page_match = re.fullmatch(r"(.+)[（(]([^（）()]*)[）)](2019)_(\d+)", stem)
    if page_match and course_name in ("ドイツ語1A(演習)", "分子生物学1"):
        subject = course_name.strip()
        teacher = normalize_teacher(page_match.group(2))
        year = page_match.group(3) + infer_term_from_subject(subject)
        page_number = int(page_match.group(4))
        page_groups = {
            "ドイツ語1A(演習)": "kuwiki-pagegroup-deutsch1a-hosomi-2019",
            "分子生物学1": "kuwiki-pagegroup-molecular-biology1-2019",
        }
        return {
            "year": year,
            "teacher": teacher,
            "subject": subject,
            "pageGroup": page_groups[subject],
            "pageNumber": page_number,
        }

    multi_year = {
        "2010,11,13分析化学2過去問": ("分析化学2", "", ("2010", "2011", "2013")),
        "日本古典講読基礎論1A06,07,08": ("日本古典講読基礎論1A", "", ("2006", "2007", "2008")),
        "日本史1A(西山)10,12,13,14": ("日本史1A", "西山", ("2010", "2012", "2013", "2014")),
        "日本史2A(元木)06,09,12": ("日本史2A", "元木", ("2006", "2009", "2012")),
        "物理学基礎論B(田中)07,08,09": ("物理学基礎論B", "田中", ("2007", "2008", "2009")),
    }
    if stem in multi_year:
        subject, teacher, years = multi_year[stem]
        return [
            {
                "year": year + infer_term_from_subject(subject),
                "teacher": teacher,
                "subject": subject,
                "idSuffix": year,
                "multiYears": ", ".join(years),
            }
            for year in years
        ]

    return None


def parse_no_year_filename(stem: str, course_name: str) -> dict | None:
    if re.search(r"(?:19|20)\d{2}", stem):
        return None
    if re.search(r"(?:19|20)[_?？]{1,2}|(?:19|20)\d[_?？]", stem):
        return None
    if re.search(r"(?<!\d)\d{2}(?:[,，、]\d{2})+(?!\d)", stem):
        return None
    if any(pattern in stem for pattern in NO_YEAR_EXCLUDED_PATTERNS) or re.search(r"問題\d|テスト\d", stem):
        return None

    paren_match = re.search(r"^(.+)[（(]([^（）()]*)[）)](.*)$", stem)
    if not paren_match:
        return None

    trailing = paren_match.group(3).strip()
    if trailing not in NO_YEAR_TRAILING_MARKERS:
        return None

    subject = paren_match.group(1).strip() or course_name.strip()
    raw_teacher = paren_match.group(2).strip()
    if is_non_teacher_paren(raw_teacher):
        subject = stem[: paren_match.end(2) + 1].strip()
        return {"year": "", "teacher": "", "subject": subject}
    return {"year": "", "teacher": normalize_teacher(raw_teacher), "subject": subject}


def parse_typed_exam_filename(stem: str, course_name: str) -> dict | None:
    lowered = stem.lower()
    if any(pattern.lower() in lowered for pattern in ANSWER_PATTERNS):
        return None
    if any(pattern in stem for pattern in NON_EXAM_TYPED_PATTERNS):
        return None

    test_type = infer_test_type(stem)
    if not test_type:
        return None

    year_match = re.search(r"((?:19|20)\d{2})(?:年度)?\s*(前期|後期|前|後)?", stem)
    if not year_match:
        return None

    year = year_match.group(1)
    explicit_term = normalize_term(year_match.group(2) or "")
    before_year = stem[: year_match.start()].strip(" 　_-.")
    after_year = stem[year_match.end() :].strip(" 　_-.")

    teacher = teacher_from_brackets(stem, year_match.start())
    if not teacher:
        teacher = teacher_after_year(after_year)

    subject = subject_from_typed_filename(stem, before_year, teacher, course_name)
    term = explicit_term or infer_term_from_subject(clean_typed_subject(before_year)) or infer_term_from_subject(subject)
    return {"year": year + term, "teacher": teacher, "subject": subject, "testType": test_type}


def infer_test_type(stem: str) -> str:
    if any(marker in stem for marker in SMALL_TEST_MARKERS):
        return "小テスト"
    if any(marker in stem for marker in REGULAR_TEST_MARKERS):
        return "定期テスト"
    return ""


def normalize_term(term: str) -> str:
    if term in ("前", "前期"):
        return "前期"
    if term in ("後", "後期"):
        return "後期"
    return ""


def teacher_from_brackets(stem: str, year_start: int) -> str:
    candidates = []
    for match in re.finditer(r"[（(［\[]([^（）()\[\]［］]*)[）)］\]]", stem):
        value = match.group(1).strip()
        if is_non_teacher_paren(value):
            continue
        if re.search(r"(?:19|20)\d{2}|年度", value) or value in ("前", "後", "前期", "後期", "法・英"):
            continue
        candidates.append((abs(match.start() - year_start), match.start(), normalize_teacher(value)))
    candidates = [candidate for candidate in candidates if candidate[2]]
    if not candidates:
        return ""
    return sorted(candidates)[0][2]


def teacher_after_year(after_year: str) -> str:
    cleaned = after_year
    for marker in SMALL_TEST_MARKERS + REGULAR_TEST_MARKERS:
        cleaned = cleaned.replace(marker, " ")
    cleaned = re.sub(r"第[一二三四五六七八九十]+回|オンライン|前期|後期|前|後|月\d|火\d|水\d|木\d|金\d", " ", cleaned)
    cleaned = re.sub(r"[\s_.,，、()（）\\-]+", " ", cleaned).strip()
    if re.fullmatch(r"[\u3400-\u9fff々ぁ-んァ-ヶー・]{1,8}", cleaned):
        return normalize_teacher(cleaned)
    return ""


def subject_from_typed_filename(stem: str, before_year: str, teacher: str, course_name: str) -> str:
    if course_name.strip():
        return course_name.strip()
    if before_year and not re.fullmatch(r"[前後]?", before_year):
        subject = clean_typed_subject(before_year)
        if subject.count("(") != subject.count(")") or subject.count("（") != subject.count("）"):
            return course_name.strip()
        if subject and not re.fullmatch(r"(?:19|20)\d{2}.*", subject):
            return subject
    return course_name.strip()


def clean_typed_subject(value: str) -> str:
    subject = value
    for marker in SMALL_TEST_MARKERS + REGULAR_TEST_MARKERS:
        subject = subject.replace(marker, "")
    subject = re.sub(r"^[前後]\)?", "", subject).strip(" 　_-.")
    return re.sub(r"[（(［\[]([^（）()\[\]［］]*)[）)］\]]\s*$", "", subject).strip()


def normalize_teacher(teacher: str) -> str:
    teacher = teacher.strip()
    if teacher in ("", "_", "不明") or teacher.lower() == "unknown":
        return ""
    separator_count = sum(teacher.count(separator) for separator in ("・", "･", "-", "ー"))
    if "他" in teacher or separator_count >= 3:
        return ""
    return teacher


def is_non_teacher_paren(value: str) -> bool:
    return value in ("文法",) or bool(re.fullmatch(r"T\d+", value))


def infer_term_from_subject(subject: str) -> str:
    normalized = re.sub(r"[（(［\[].*[）)］\]]$", "", subject).strip()
    if normalized.endswith(FRONT_TERM_SUFFIXES):
        return "前期"
    if normalized.endswith(BACK_TERM_SUFFIXES):
        return "後期"
    return ""


def build_exam(course: dict, file_item: dict, parsed: dict) -> dict:
    notes = [
        "京都大学",
        f"京大wiki科目コード: {course.get('code') or '未登録'}",
        f"京大wiki分野: {course.get('field') or '未登録'}",
        f"京大wiki科目名: {course.get('name')}",
        f"ファイル名: {file_item.get('name')}",
    ]
    if file_item.get("folderPath"):
        notes.append(f"フォルダ階層: {file_item['folderPath']}")
    if parsed.get("pageNumber"):
        notes.append(f"ページ分割ファイル: {parsed['pageNumber']}ページ目")
    if parsed.get("multiYears"):
        notes.append(f"複数年度ファイル: {parsed['multiYears']}")
    exam = {
        "id": f"kuwiki-{file_item['id']}" + (f"-{parsed['idSuffix']}" if parsed.get("idSuffix") else ""),
        "year": parsed["year"],
        "teacher": parsed["teacher"],
        "subject": parsed["subject"],
        "group": course.get("field", ""),
        "testType": parsed.get("testType", "過去問"),
        "sourceSite": "京大wiki",
        "localFile": "未保存",
        "driveUrl": file_item["url"],
        "notes": " / ".join(notes),
    }
    if parsed.get("pageGroup"):
        exam["pageGroup"] = parsed["pageGroup"]
        exam["pageNumber"] = parsed["pageNumber"]
    return exam


def discard_kuwiki_records(exams: list[dict]) -> list[dict]:
    return [exam for exam in exams if not str(exam.get("id", "")).startswith("kuwiki-")]


def note_value(notes: str, label: str) -> str:
    prefix = f"{label}: "
    for part in notes.split(" / "):
        if part.startswith(prefix):
            return part.removeprefix(prefix)
    return ""


def curl_json(url: str) -> list[dict]:
    text = curl_text(url)
    return json.loads(text)


def curl_text(url: str) -> str:
    try:
        result = run(
            ["curl", "-LsA", USER_AGENT, url],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except TimeoutExpired as error:
        raise RuntimeError(f"Driveフォルダの取得がタイムアウトしました: {url}") from error
    except CalledProcessError as error:
        raise RuntimeError(error.stderr.strip() or f"curl failed: {url}") from error
    return result.stdout


def read_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def unique(values) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def unique_files(files: list[dict]) -> list[dict]:
    seen = set()
    result = []
    for file_item in files:
        if file_item["id"] in seen:
            continue
        seen.add(file_item["id"])
        result.append(file_item)
    return result


def unique_folders(folders: list[dict]) -> list[dict]:
    seen = set()
    result = []
    for folder_item in folders:
        key = folder_item.get("id") or folder_item.get("url") or folder_item.get("folderPath")
        if key in seen:
            continue
        seen.add(key)
        result.append(folder_item)
    return result


if __name__ == "__main__":
    main()
