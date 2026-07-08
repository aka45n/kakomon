from __future__ import annotations

from pathlib import Path
from subprocess import CalledProcessError, TimeoutExpired, run
import argparse
import html
import json
import re
import sys
import time

from import_kuwiki import (
    FOLDER_MIME_TYPE,
    SUPPORTED_EXTENSIONS,
    build_drive_file,
    clear_paged_file_parses,
    infer_test_type,
    is_ignored_file,
    normalize_teacher,
    parse_exam_filename,
    parse_folder_path_filename,
    read_json,
    safe_id_part,
)


ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "exams.json"
UNRESOLVED_PATH = ROOT / "data" / "kuinfo2020_unresolved.json"
KUINFO2020_ROOT = "https://drive.google.com/drive/folders/10V3htAY7umRt8SR9FeuvP8wk0t86snaj"
USER_AGENT = "Mozilla/5.0 (compatible; kakomon-kuinfo2020-importer/1.0)"

ROOT_GROUPS = {
    "英語": "外国語群",
    "2外": "外国語群",
    "健康群": "健康群",
    "人社(自由にフォルダを作ってください)": "人社群",
    "自然": "自然群",
    "情報学科目": "情報群",
    "専門(共通)": "工学部専門科目",
    "専門(数理)": "工学部専門科目",
    "専門(計算機)": "工学部専門科目",
}

SKIP_ROOT_FOLDERS = {
    "院試過去問",
    "他学部聴講",
    "本棚",
    "例のアレ",
}

NON_EXAM_FOLDER_PATTERNS = (
    "講義",
    "授業",
    "資料",
    "ノート",
    "レジュメ",
    "レジメ",
    "シケプリ",
    "教科書",
    "本棚",
    "参考",
    "スライド",
    "プリント",
    "課題",
    "レポート",
    "レポート",
    "rep_files",
)

FOLDER_METADATA_PATTERNS = (
    r"^(?:19|20)\d{2}(?:年度)?(?:前期|後期)?$",
    r"^(?:19|20)\d{2}[（(].*[）)]$",
    r"^(?:前期|後期)$",
    r"^(?:中間|期末|小テスト|試験|過去問|解答|解説)$",
    r"^第?\d+回$",
    r"^\d+(?:st|nd|rd|th)$",
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Import Kyoto University exams from KUInfo2020.")
    parser.add_argument("--sleep", type=float, default=0.05, help="Delay between Drive folder requests.")
    parser.add_argument("--limit-folders", type=int, default=0, help="Stop after crawling this many folders.")
    parser.add_argument("--dry-run", action="store_true", help="Crawl and parse without writing files.")
    args = parser.parse_args()

    crawl = CrawlState(args.sleep, args.limit_folders)
    files, unsupported, skipped_folders = crawl.fetch_drive_files(KUINFO2020_ROOT)

    existing = discard_kuinfo2020_records(read_json(DATA_PATH, []))
    by_id = {exam["id"]: exam for exam in existing}
    unresolved = []
    imported = 0

    unresolved.extend(crawl.fetch_errors)
    unresolved.extend(
        {
            "folder": folder,
            "reason": "今回は対象外のフォルダまたは講義資料系フォルダとしてスキップしました。",
        }
        for folder in skipped_folders
    )
    unresolved.extend(
        {
            "file": report_file(file_item),
            "reason": "未対応の拡張子です。",
        }
        for file_item in unsupported
        if not should_skip_file(file_item)
    )

    files_by_course = {}
    for file_item in files:
        course_name = infer_course_name(file_item)
        files_by_course.setdefault(course_name, []).append(file_item)

    paged_parses = {}
    for course_name, course_files in files_by_course.items():
        paged_parses.update(clear_paged_file_parses(course_files, course_name))

    for file_item in files:
        if should_skip_file(file_item):
            continue
        group = infer_group(file_item)
        if not group:
            unresolved.append(
                {
                    "file": report_file(file_item),
                    "reason": "KUInfo2020の階層から科目群を判定できませんでした。",
                }
            )
            continue

        course_name = infer_course_name(file_item)
        parsed_items = (
            paged_parses.get(file_item["id"])
            or parse_kuinfo2020_folder_filename(file_item, course_name)
            or parse_folder_path_filename(file_item, course_name)
            or parse_exam_filename(file_item["name"], course_name)
        )
        if not parsed_items:
            unresolved.append(
                {
                    "file": report_file(file_item),
                    "reason": "ファイル名またはフォルダ階層から年度・学期・教師名を十分に判定できませんでした。",
                }
            )
            continue

        if isinstance(parsed_items, dict):
            parsed_items = [parsed_items]
        for parsed in parsed_items:
            if not parsed.get("year") or not parsed.get("subject"):
                unresolved.append(
                    {
                        "file": report_file(file_item),
                        "parsed": parsed,
                        "reason": "年度または科目名が空欄のため自動登録しませんでした。",
                    }
                )
                continue
            exam = build_exam(file_item, parsed, group, course_name)
            if exam["id"] not in by_id:
                existing.append(exam)
                by_id[exam["id"]] = exam
                imported += 1

    existing.sort(key=lambda item: (item.get("subject", ""), item.get("year", ""), item.get("teacher", ""), item.get("id", "")))
    unresolved.sort(key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True))

    if not args.dry_run:
        DATA_PATH.write_text(json.dumps(existing, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        UNRESOLVED_PATH.write_text(json.dumps(unresolved, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"folders={crawl.folder_count} files={len(files)} unsupported={len(unsupported)} "
        f"imported={imported} total={len(existing)} unresolved={len(unresolved)}",
        flush=True,
    )


class CrawlState:
    def __init__(self, sleep: float, limit_folders: int):
        self.sleep = sleep
        self.limit_folders = limit_folders
        self.folder_count = 0
        self.visited = set()
        self.fetch_errors = []

    def fetch_drive_files(self, folder_url: str, folder_path: tuple[str, ...] = ()) -> tuple[list[dict], list[dict], list[dict]]:
        if folder_url in self.visited:
            return [], [], []
        if self.limit_folders and self.folder_count >= self.limit_folders:
            return [], [], []
        self.visited.add(folder_url)
        self.folder_count += 1
        if self.folder_count % 50 == 0:
            print(f"crawled folders={self.folder_count} path={' / '.join(folder_path) or 'root'}", file=sys.stderr, flush=True)

        try:
            page = curl_text(folder_url)
        except RuntimeError as error:
            self.fetch_errors.append(
                {
                    "folder": build_folder(folder_url.rsplit("/", 1)[-1], folder_path[-1] if folder_path else "ルートフォルダ", folder_path),
                    "reason": str(error),
                }
            )
            return [], [], []
        file_markers = list(
            re.finditer(
                r'\[\[null,"(?P<id>[A-Za-z0-9_-]+)"\],null,null,null,"(?P<mime>[^"]+)"',
                page,
            )
        )
        files = []
        unsupported_files = []
        skipped_folders = []
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
                child_path = folder_path + (name,)
                folder = build_folder(file_id, name, child_path)
                if should_skip_folder(child_path):
                    skipped_folders.append(folder)
                    continue
                child_url = f"https://drive.google.com/drive/folders/{file_id}"
                child_files, child_unsupported, child_skipped = self.fetch_drive_files(child_url, child_path)
                files.extend(child_files)
                unsupported_files.extend(child_unsupported)
                skipped_folders.extend(child_skipped)
                if self.sleep:
                    time.sleep(self.sleep)
                continue

            file_item = build_drive_file(file_id, name, folder_path)
            if Path(name).suffix.lower() in SUPPORTED_EXTENSIONS:
                files.append(file_item)
            else:
                unsupported_files.append(file_item)

        return unique_files(files), unique_files(unsupported_files), unique_folders(skipped_folders)


def should_skip_folder(folder_path: tuple[str, ...]) -> bool:
    if not folder_path:
        return False
    if folder_path[0] in SKIP_ROOT_FOLDERS:
        return True
    return any(any(pattern in part for pattern in NON_EXAM_FOLDER_PATTERNS) for part in folder_path)


def should_skip_file(file_item: dict) -> bool:
    folder_path = file_item.get("folderPath", "")
    if folder_path and should_skip_folder(tuple(part.strip() for part in folder_path.split("/") if part.strip())):
        return True
    return is_ignored_file(file_item.get("name", "")) or any(pattern in file_item.get("name", "") for pattern in NON_EXAM_FOLDER_PATTERNS)


def infer_group(file_item: dict) -> str:
    parts = folder_parts(file_item)
    if not parts:
        return ""
    return ROOT_GROUPS.get(parts[0], "")


def infer_course_name(file_item: dict) -> str:
    parts = folder_parts(file_item)
    candidates = parts[1:] if parts and parts[0] in ROOT_GROUPS else parts
    for part in reversed(candidates):
        cleaned = clean_course_folder_name(part)
        if cleaned and not is_metadata_folder(cleaned):
            return cleaned
    stem = Path(file_item["name"]).with_suffix("").name
    stem = re.sub(r"((?:19|20)\d{2}).*$", "", stem).strip(" 　_-.")
    stem = re.sub(r"[（(][^（）()]*[）)]$", "", stem).strip()
    return stem


def parse_kuinfo2020_folder_filename(file_item: dict, course_name: str) -> dict | None:
    path = Path(file_item["name"])
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        return None
    stem = path.with_suffix("").name.strip()
    folder_text = " ".join(folder_parts(file_item))
    text = f"{folder_text} {stem}"

    year_match = re.search(r"((?:19|20)\d{2})(?:年度)?(?:[.．_・\s-]*)(前期|後期|前|後|[AaBb])?", text)
    if not year_match:
        return None
    term = normalize_term(year_match.group(2) or "") or infer_term_from_context(course_name, text)
    if not term:
        return None

    teacher = teacher_from_text(stem, year_match.group(1)) or teacher_from_text(folder_text, year_match.group(1))
    subject = course_name.strip()
    test_type = infer_test_type(text) or "定期テスト"
    return {
        "year": year_match.group(1) + term,
        "teacher": teacher,
        "subject": subject,
        "testType": test_type,
    }


def infer_term_from_context(course_name: str, text: str) -> str:
    if re.search(r"(?:^|[\\s_/・-])A(?:$|[\\s_/・-])|Ⅰ|I$", course_name):
        return "前期"
    if re.search(r"(?:^|[\\s_/・-])B(?:$|[\\s_/・-])|Ⅱ|II$", course_name):
        return "後期"
    if "前期" in text:
        return "前期"
    if "後期" in text:
        return "後期"
    return ""


def teacher_from_text(text: str, year: str) -> str:
    for match in re.finditer(r"[（(]([^（）()]*)[）)]", text):
        value = match.group(1).strip()
        if not value or year in value or re.search(r"自由にフォルダ|数理|計算機|共通|前期|後期|中間|期末|問題|解答|演習|文法|実習|概要", value):
            continue
        return normalize_teacher(value)
    after_year = re.split(re.escape(year), text, maxsplit=1)
    if len(after_year) == 2:
        candidate = re.sub(r"前期|後期|中間|期末|試験|問題|解答|小テスト|第\\d+回", " ", after_year[1])
        candidate = re.sub(r"[\\s_.,，、()（）\\-]+", " ", candidate).strip()
        if re.fullmatch(r"[一-龥々ぁ-んァ-ヶー・]{1,8}", candidate):
            return normalize_teacher(candidate)
    return ""


def normalize_term(term: str) -> str:
    if term in ("前", "前期", "A", "a"):
        return "前期"
    if term in ("後", "後期", "B", "b"):
        return "後期"
    return ""


def clean_course_folder_name(value: str) -> str:
    value = re.sub(r"^[\\s_\\-・]+|[\\s_\\-・]+$", "", value)
    return re.sub(r"[（(].*?自由にフォルダを作ってください.*?[）)]", "", value).strip()


def is_metadata_folder(value: str) -> bool:
    if any(re.fullmatch(pattern, value) for pattern in FOLDER_METADATA_PATTERNS):
        return True
    return bool(re.fullmatch(r"[A-Z]群?|[１２12]回生|[一二三四五六七八九十]+回", value))


def build_exam(file_item: dict, parsed: dict, group: str, course_name: str) -> dict:
    notes = [
        "京都大学",
        f"KUInfo2020科目名候補: {course_name}",
        f"ファイル名: {file_item.get('name')}",
    ]
    if file_item.get("folderPath"):
        notes.append(f"フォルダ階層: {file_item['folderPath']}")
    if parsed.get("pageNumber"):
        notes.append(f"ページ分割ファイル: {parsed['pageNumber']}ページ目")
    exam = {
        "id": f"kuinfo2020-{file_item['id']}" + (f"-{parsed['idSuffix']}" if parsed.get("idSuffix") else ""),
        "year": parsed["year"],
        "teacher": parsed.get("teacher", ""),
        "subject": parsed["subject"],
        "group": group,
        "testType": parsed.get("testType", "定期テスト"),
        "sourceSite": "KUInfo2020",
        "localFile": "未保存",
        "driveUrl": file_item["url"],
        "notes": " / ".join(notes),
    }
    if parsed.get("pageGroup"):
        exam["pageGroup"] = "kuinfo2020-" + safe_id_part(parsed["pageGroup"])
        exam["pageNumber"] = parsed["pageNumber"]
    return exam


def report_file(file_item: dict) -> dict:
    return {
        "id": file_item.get("id"),
        "name": file_item.get("name"),
        "url": file_item.get("url"),
        "folderPath": file_item.get("folderPath", ""),
    }


def build_folder(folder_id: str, name: str, folder_path: tuple[str, ...]) -> dict:
    return {
        "id": folder_id,
        "name": name or "未登録",
        "url": f"https://drive.google.com/drive/folders/{folder_id}",
        "folderPath": " / ".join(folder_path),
    }


def folder_parts(file_item: dict) -> list[str]:
    return [part.strip() for part in file_item.get("folderPath", "").split("/") if part.strip()]


def discard_kuinfo2020_records(exams: list[dict]) -> list[dict]:
    return [exam for exam in exams if not str(exam.get("id", "")).startswith("kuinfo2020-")]


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
    for folder in folders:
        if folder["id"] in seen:
            continue
        seen.add(folder["id"])
        result.append(folder)
    return result


if __name__ == "__main__":
    main()
