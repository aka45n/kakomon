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
IMAGE_EXTENSIONS = (
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".tif",
    ".tiff",
)
PAGE_GROUP_EXTENSIONS = IMAGE_EXTENSIONS + (".pdf",)
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
    "課題",
    "対策",
    "宿題",
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
COURSE_GROUP_MAP = {
    "全学：自然": "自然群",
    "理：物理": "自然群",
    "工：物工": "自然群",
    "理：化学": "自然群",
    "理：生物": "自然群",
    "理：数学": "自然群",
    "理：地物": "自然群",
    "工：共通": "自然群",
    "理：境界": "自然群",
    "理：宇物": "自然群",
    "理：地鉱": "自然群",
    "工：地球工": "自然群",
    "工：工化": "自然群",
    "農：森林": "自然群",
    "農：応生": "自然群",
    "工：電電": "自然群",
    "農：資源": "自然群",
    "農：共通": "自然群",
    "工：建築": "自然群",
    "農：食品": "自然群",
    "全学：人社": "人社群",
    "教育：教職": "人社群",
    "教育：心理": "人社群",
    "法：法": "人社群",
    "総人：総人": "人社群",
    "文：文": "人社群",
    "経済：経済": "人社群",
    "教育：現教": "人社群",
    "全学：外国語": "外国語群",
    "全学：健康": "健康群",
    "全学：情報": "情報群",
    "工：情報": "情報群",
    "全学：キャリア": "キャリア形成科目群",
    "全学：統合": "統合科学科目群",
}
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


def course_group(value: str) -> str:
    return COURSE_GROUP_MAP.get(value, value)
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
PAGE_BASE_TERM_OVERRIDES = {
    "基礎物理化学(熱力学)(渡邊)2016": "",
    "基礎物理化学(量子論)(渡邊)2016": "",
    "量子物理学(中家)2016": "後期",
}

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

        paged_parses = clear_paged_file_parses(files, course["name"])
        for file_item in files:
            if is_ignored_file(file_item["name"]):
                continue
            parsed_items = (
                paged_parses.get(file_item["id"])
                or parse_folder_path_filename(file_item, course["name"])
                or parse_exam_filename(file_item["name"], course["name"])
            )
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
        "field": course_group(course.get("field") or "未登録"),
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
        return (
            parse_year_not_at_end_filename(stem, course_name)
            or parse_typed_exam_filename(stem, course_name)
            or parse_no_year_filename(stem, course_name)
        )

    before_year = stem[: year_match.start()].strip()
    teacher = ""
    subject = course_name.strip()

    paren_match = re.search(r"[（(]([^（）()]*)[）)]\s*$", before_year)
    if paren_match:
        teacher = normalize_teacher(paren_match.group(1))
        subject_from_file = before_year[: paren_match.start()].strip()
        if subject_from_file:
            subject = subject_from_file

    term = year_match.group(2) or infer_term_from_subject(subject)
    if not term:
        return None
    year = year_match.group(1) + term
    return {"year": year, "teacher": teacher, "subject": subject}


def is_material_file(filename: str) -> bool:
    if any(pattern in filename for pattern in MATERIAL_PATTERNS):
        return True
    return any(re.search(pattern, filename, re.IGNORECASE) for pattern in MATERIAL_FILENAME_PATTERNS)


def is_report_file(filename: str) -> bool:
    return any(pattern.lower() in filename.lower() for pattern in REPORT_PATTERNS)


def is_ignored_file(filename: str) -> bool:
    if filename == "中国語2B(黄明月)2020中間課題.pdf":
        return False
    return filename.startswith(IGNORE_FILENAME_PREFIXES) or is_material_file(filename) or is_report_file(filename)


def parse_special_filename(stem: str, course_name: str):
    if stem == "中国語2B(黄明月)2020中間課題":
        return {"year": "2020後期", "teacher": "黄明月", "subject": "中国語2B", "testType": "小テスト"}

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


def clear_paged_file_parses(files: list[dict], course_name: str) -> dict[str, dict]:
    candidates = []
    for file_item in files:
        path = Path(file_item["name"])
        if path.suffix.lower() not in PAGE_GROUP_EXTENSIONS:
            continue
        match = page_suffix_match(path.with_suffix("").name.strip()) or trailing_page_suffix_match(path.with_suffix("").name.strip())
        if not match:
            continue
        page_number = int(match["page_number"])
        if page_number > 20:
            continue
        candidates.append(
            {
                "file": file_item,
                "base": match["base"].strip(" _-"),
                "pageNumber": page_number,
            }
        )

    grouped = {}
    for candidate in candidates:
        key = (course_name, candidate["base"])
        grouped.setdefault(key, []).append(candidate)

    parses = {}
    for (course_key, base), group in grouped.items():
        pages = [item["pageNumber"] for item in group]
        unique_pages = sorted(set(pages))
        if len(group) < 2 or len(unique_pages) != len(group):
            continue
        if unique_pages != list(range(1, len(unique_pages) + 1)):
            continue
        parsed = parse_base_metadata(base, course_key)
        if not parsed:
            continue
        page_group = "kuwiki-pagegroup-" + safe_id_part(course_key) + "-" + safe_id_part(base)
        for item in group:
            parses[item["file"]["id"]] = {
                **parsed,
                "pageGroup": page_group,
                "pageNumber": item["pageNumber"],
            }
    return parses


def page_suffix_match(stem: str) -> dict | None:
    match = re.fullmatch(
        r"(?P<base>.*?(?:19|20)\d{2}(?:年?度?)?(?:[.．_・])?(?:前期|後期|前|後|[AaBb])?)[\s_\-]*(?:\((?P<p1>\d+)\)|[（(](?P<p2>\d+)[）)]|_(?P<p3>\d+)|(?P<p4>\d+))",
        stem,
    )
    if not match:
        return None
    return {
        "base": match.group("base"),
        "page_number": next(match.group(key) for key in ("p1", "p2", "p3", "p4") if match.group(key)),
    }


def trailing_page_suffix_match(stem: str) -> dict | None:
    match = re.fullmatch(r"(?P<base>.*\D)(?P<page_number>\d{1,2})", stem)
    if not match or not re.search(r"(?:19|20)\d{2}", match.group("base")):
        return None
    base = match.group("base").rstrip(" _-")
    if re.search(r"No\.?$", base, re.IGNORECASE):
        return None
    return {"base": base, "page_number": match.group("page_number")}


def parse_base_metadata(base: str, course_name: str) -> dict | None:
    year_match = re.search(r"((?:19|20)\d{2})(?:年?度?)?(?:[.．_・])?(前期|後期|前|後|[AaBb])?", base)
    if not year_match:
        return None
    explicit_term = normalize_term(year_match.group(2) or "")
    before_year = base[: year_match.start()]
    teacher = ""
    for match in re.finditer(r"[（(]([^（）()]*)[）)]", before_year):
        value = match.group(1).strip()
        if value in ("文法", "演習", "実習") or is_non_teacher_paren(value):
            continue
        teacher = normalize_teacher(value)
    subject = course_name.strip() or clean_typed_subject(before_year)
    term = PAGE_BASE_TERM_OVERRIDES.get(base)
    if term is None:
        if year_match.group(2) in ("A", "a", "B", "b"):
            term = infer_term_from_subject(subject) or explicit_term
        else:
            term = explicit_term or infer_term_from_subject(before_year) or infer_term_from_subject(subject)
    if not term and base not in PAGE_BASE_TERM_OVERRIDES:
        return None
    return {"year": year_match.group(1) + term, "teacher": teacher, "subject": subject}


def safe_id_part(value: str) -> str:
    value = str(value).strip()
    value = re.sub(r"[^0-9A-Za-z一-龥ぁ-んァ-ヶー々〆〤._-]+", "-", value)
    return re.sub(r"-+", "-", value).strip("-._") or "group"


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
    if not term:
        return None
    return {"year": year + term, "teacher": teacher, "subject": subject, "testType": test_type}


def parse_folder_path_filename(file_item: dict, course_name: str) -> dict | None:
    folder_path = file_item.get("folderPath", "")
    if not folder_path or is_material_context(folder_path):
        return None

    metadata = parse_folder_path_metadata(folder_path, course_name)
    if not metadata:
        return None

    stem = Path(file_item["name"]).with_suffix("").name.strip()
    if not looks_exam_like_from_folder(stem, folder_path):
        return None

    metadata["testType"] = infer_test_type(stem) or "定期テスト"
    return metadata


def parse_folder_path_metadata(folder_path: str, course_name: str) -> dict | None:
    text = " ".join(part.strip() for part in folder_path.split("/") if part.strip())
    year_match = re.search(r"((?:19|20)\d{2})(?:年?度?)?(?:[.．_・ ]*)?(前期|後期|前|後|[AaBb])?", text)
    if not year_match:
        return None

    year = year_match.group(1)
    term = normalize_term(year_match.group(2) or "") or infer_term_from_subject(course_name) or infer_term_from_subject(text)
    teacher = teacher_from_folder_path(text, year_match)
    return {"year": year + term, "teacher": teacher, "subject": course_name.strip()}


def teacher_from_folder_path(text: str, year_match) -> str:
    for match in re.finditer(r"[（(]([^（）()]*)[）)]", text):
        value = match.group(1).strip()
        if not value or is_non_teacher_paren(value) or re.search(r"(?:19|20)\d{2}|年度|前期|後期|問題|解答", value):
            continue
        return normalize_teacher(value.replace("、", "・").replace("_", "・"))

    after_year = text[year_match.end() :].strip()
    match = re.fullmatch(r"([一-龥々ぁ-んァ-ヶー・、]{1,8})", after_year)
    if not match:
        return ""
    value = match.group(1).replace("、", "・")
    if "・" not in value and re.fullmatch(r"[一-龥々]{3,}", value):
        value = value[:2]
    return normalize_teacher(value)


def is_material_context(value: str) -> bool:
    return any(pattern in value for pattern in MATERIAL_PATTERNS + REPORT_PATTERNS)


def looks_exam_like_from_folder(stem: str, folder_path: str = "") -> bool:
    lowered = stem.lower()
    if any(marker in folder_path for marker in SMALL_TEST_MARKERS + REGULAR_TEST_MARKERS + ANSWER_PATTERNS):
        return True
    markers = SMALL_TEST_MARKERS + REGULAR_TEST_MARKERS + ANSWER_PATTERNS + (
        "prob",
        "exam",
        "solution",
        "solutions",
        "ans",
        "sa_",
        "sma_",
    )
    return any(marker.lower() in lowered for marker in markers)


def parse_year_not_at_end_filename(stem: str, course_name: str) -> dict | None:
    if looks_like_timestamp_filename(stem):
        return None

    year_match = re.search(r"((?:19|20)\d{2})(?:年?度?)?(?:[.．_・])?(前期|後期|前|後|[AaBb])?", stem)
    if not year_match:
        return None

    suffix_term = normalize_term(year_match.group(2) or "")
    subject_term = infer_term_from_subject(course_name)
    if year_match.group(2) in ("A", "a", "B", "b"):
        term = subject_term or suffix_term
    else:
        term = suffix_term or subject_term
    if not term:
        return None

    teacher = teacher_from_brackets(stem, year_match.start())
    test_type = infer_test_type(stem) or "定期テスト"
    return {
        "year": year_match.group(1) + term,
        "teacher": teacher,
        "subject": course_name.strip(),
        "testType": test_type,
    }


def looks_like_timestamp_filename(stem: str) -> bool:
    return bool(
        re.fullmatch(r"(?:IMG|1MG)?_?\d{8}[_-]?\d{6}.*", stem, re.IGNORECASE)
        or re.fullmatch(r"\d{14,}.*", stem)
        or re.fullmatch(r"\d{8}[_-]\d{6}.*", stem)
    )


def infer_test_type(stem: str) -> str:
    if any(marker in stem for marker in SMALL_TEST_MARKERS):
        return "小テスト"
    if any(marker in stem for marker in REGULAR_TEST_MARKERS):
        return "定期テスト"
    return ""


def normalize_term(term: str) -> str:
    if term in ("前", "前期", "A", "a"):
        return "前期"
    if term in ("後", "後期", "B", "b"):
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
    normalized = re.sub(r"[（(［\[]+$", "", normalized).strip()
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
        "group": course_group(course.get("field", "")),
        "testType": parsed.get("testType", "定期テスト"),
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
