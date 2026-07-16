from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
from subprocess import CalledProcessError, TimeoutExpired, run
from urllib.parse import quote, unquote, urljoin, urlparse
import argparse
import html
import json
import re
import sys
import time

from import_kuwiki import (
    SUPPORTED_EXTENSIONS,
    build_drive_file,
    infer_term_from_subject,
    infer_test_type,
    is_ignored_file,
    normalize_teacher,
    parse_exam_filename,
    safe_id_part,
)


ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "exams.json"
UNRESOLVED_PATH = ROOT / "data" / "ku1025_unresolved.json"
BASE_URL = "https://ku1025.netlify.app/"
USER_AGENT = "Mozilla/5.0 (compatible; kakomon-ku1025-importer/1.0)"
ENTRY_PAGES = (
    "全学共通科目.html",
    "工学部専門科目.html",
    "他学部聴講.html",
    "大学院授業科目.html",
    "大学院入試問題.html",
)
DIRECT_GROUP_PAGES = {
    "人社群": "人社群",
    "情報群": "情報群",
    "自然群": "自然群",
    "言語（E2含む）": "外国語群",
}
SPECIALTY_GROUP_PAGES = {
    "工学部専門科目": "工学部専門科目",
    "地球工学科専門科目": "工学部専門科目",
    "建築学科専門科目": "工学部専門科目",
    "物理工学科専門科目": "工学部専門科目",
    "理工化学科専門科目": "工学部専門科目",
    "電気電子工学科専門科目": "工学部専門科目",
    "情報学科専門科目": "工学部専門科目",
    "あ・か行": "工学部専門科目",
    "さ〜ら行": "工学部専門科目",
    "先端化学コース": "工学部専門科目",
    "創成化学コース": "工学部専門科目",
    "化学プロセス工学コース": "工学部専門科目",
    "理工化学科共通・分類不明": "工学部専門科目",
    "工業化学科共通・分類不明": "工学部専門科目",
}
SUBJECT_GROUP_OVERRIDES = {
    "応用電磁気学": "工学部専門科目",
}
NATURAL_ROOT_PAGES = (
    "大学院授業科目",
    "大学院入試問題",
)
SKIP_SITE_PATHS = {
    "",
    "/",
    "index.html",
    "upload",
    "upload.html",
    "caution",
    "caution.html",
    "detail",
    "detail.html",
    "privacy_policy",
    "privacy_policy.html",
    "menseki",
    "menseki.html",
    "ku1023_index",
    "ku1023_index.html",
}


class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self._active_href = None
        self._active_text = []
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a":
            self._active_href = attrs.get("href")
            self._active_text = []
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag == "a" and self._active_href:
            self.links.append({"href": self._active_href, "text": "".join(self._active_text).strip()})
            self._active_href = None
            self._active_text = []
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._active_href is not None:
            self._active_text.append(data)
        if self._in_title:
            self.title += data


def main() -> None:
    parser = argparse.ArgumentParser(description="Import Kyoto University exams from KU1025.")
    parser.add_argument("--sleep", type=float, default=0.08, help="Delay between KU1025 page requests.")
    parser.add_argument("--limit-pages", type=int, default=0, help="Stop after crawling this many pages.")
    args = parser.parse_args()

    pages, files, fetch_errors = crawl_site(args.sleep, args.limit_pages)
    existing = discard_ku1025_records(read_json(DATA_PATH, []))
    by_id = {exam["id"]: exam for exam in existing}
    unresolved = []
    unresolved.extend(fetch_errors)
    imported = 0

    by_page = {}
    for file_item in files:
        by_page.setdefault(file_item["pageUrl"], []).append(file_item)

    for page_url, page_files in sorted(by_page.items(), key=lambda item: item[0]):
        page = pages[page_url]
        group = infer_group(page)

        paged_parses = clear_ku1025_paged_file_parses(page_files, page["courseName"])
        for file_item in page_files:
            if is_ignored_file(file_item["name"]):
                continue
            parsed_items = paged_parses.get(file_item["id"]) or parse_ku1025_filename(file_item["name"], page["courseName"])
            if not parsed_items:
                unresolved.append(
                    {
                        "page": report_page(page),
                        "file": report_file(file_item),
                        "reason": "ファイル名から年度または教師名を判定できませんでした。",
                    }
                )
                continue
            if isinstance(parsed_items, dict):
                parsed_items = [parsed_items]
            for parsed in parsed_items:
                item_group = group or infer_group_from_subject(parsed.get("subject", "")) or infer_group_from_subject(file_item.get("name", ""))
                if not item_group:
                    unresolved.append(
                        {
                            "page": report_page(page),
                            "file": report_file(file_item),
                            "reason": "KU1025の階層から科目群を判定できませんでした。",
                        }
                    )
                    continue
                exam = build_exam(page, file_item, parsed, item_group)
                if exam["id"] not in by_id:
                    existing.append(exam)
                    by_id[exam["id"]] = exam
                    imported += 1

    existing.sort(key=lambda item: (item.get("subject", ""), item.get("year", ""), item.get("teacher", ""), item.get("id", "")))
    DATA_PATH.write_text(json.dumps(existing, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    UNRESOLVED_PATH.write_text(json.dumps(unresolved, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"pages={len(pages)} files={len(files)} imported={imported} total={len(existing)} unresolved={len(unresolved)}")


def crawl_site(sleep: float, limit_pages: int = 0) -> tuple[dict[str, dict], list[dict], list[dict]]:
    queue = [normalize_site_url(urljoin(BASE_URL, page)) for page in ENTRY_PAGES]
    pages = {}
    files = []
    fetch_errors = []

    while queue:
        url = queue.pop(0)
        if url in pages:
            continue
        if limit_pages and len(pages) >= limit_pages:
            break
        try:
            text = curl_text(url)
        except RuntimeError as error:
            fetch_errors.append({"page": {"url": url}, "reason": str(error)})
            continue
        parser = LinkParser()
        parser.feed(text)
        title = page_title(parser.title, url)
        page = {
            "url": url,
            "title": title,
            "courseName": title,
            "parentUrl": None,
            "parentTitle": "",
        }
        pages[url] = page
        if len(pages) % 25 == 0:
            print(f"crawled pages={len(pages)} queued={len(queue)} files={len(files)}", file=sys.stderr, flush=True)

        for link in parser.links:
            href = html.unescape(link["href"])
            absolute = urljoin(url, href)
            if is_drive_file_url(absolute):
                file_item = drive_file_from_link(absolute, link["text"], page)
                if file_item:
                    files.append(file_item)
                continue
            absolute = normalize_site_url(absolute)
            if not is_site_page(absolute):
                continue
            if is_back_link(link["text"]):
                page["parentUrl"] = absolute
                page["parentTitle"] = back_link_parent_title(link["text"])
                continue
            if absolute not in pages and absolute not in queue:
                queue.append(absolute)
        if queue and sleep:
            time.sleep(sleep)

    fill_parent_titles(pages)
    return pages, unique_file_items(files), fetch_errors


def page_title(raw_title: str, url: str) -> str:
    title = raw_title.strip()
    if title.startswith("KU1025-"):
        title = title.removeprefix("KU1025-")
    if title.endswith("-KU1025"):
        title = title.removesuffix("-KU1025")
    if title and title != "KU1025":
        return title
    return Path(unquote(urlparse(url).path)).stem or "KU1025"


def normalize_site_url(url: str) -> str:
    parsed = urlparse(url)
    path = unquote(parsed.path)
    if not path or path == "/":
        path = "/"
    return parsed._replace(scheme="https", netloc="ku1025.netlify.app", path=path, params="", query="", fragment="").geturl()


def is_site_page(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.netloc != "ku1025.netlify.app":
        return False
    path = unquote(parsed.path).lstrip("/")
    if path in SKIP_SITE_PATHS:
        return False
    return not Path(path).suffix or Path(path).suffix.lower() == ".html"


def is_drive_file_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.netloc == "drive.google.com" and "/file/d/" in parsed.path


def drive_file_from_link(url: str, text: str, page: dict) -> dict | None:
    match = re.search(r"/file/d/([^/?#]+)", urlparse(url).path)
    if not match:
        return None
    filename = re.sub(r"\s+", " ", text).strip()
    if not filename or filename.lower() == "tweet":
        return None
    file_item = build_drive_file(match.group(1), filename)
    file_item["url"] = f"https://drive.google.com/file/d/{file_item['id']}/view"
    file_item["pageUrl"] = page["url"]
    file_item["pageTitle"] = page["title"]
    if Path(filename).suffix.lower() not in SUPPORTED_EXTENSIONS:
        file_item["unsupported"] = True
    return file_item


def is_back_link(text: str) -> bool:
    return "に戻る" in text or "indexに戻る" in text or "KU1025公開に戻る" in text


def back_link_parent_title(text: str) -> str:
    text = re.sub(r"に戻る$", "", text.strip())
    if text in ("index", "KU1025公開"):
        return ""
    return text


def fill_parent_titles(pages: dict[str, dict]) -> None:
    for page in pages.values():
        parent_url = page.get("parentUrl")
        if parent_url and parent_url in pages:
            page["parentTitle"] = pages[parent_url]["title"]
    for page in pages.values():
        page["parentChain"] = parent_chain(page, pages)


def parent_chain(page: dict, pages: dict[str, dict]) -> list[str]:
    chain = []
    seen = set()
    parent_url = page.get("parentUrl")
    while parent_url and parent_url in pages and parent_url not in seen:
        seen.add(parent_url)
        parent = pages[parent_url]
        chain.append(parent.get("title", ""))
        parent_url = parent.get("parentUrl")
    return chain


def infer_group(page: dict) -> str:
    subject_group = SUBJECT_GROUP_OVERRIDES.get(page.get("courseName", "").strip())
    if subject_group:
        return subject_group
    titles = page_ancestry_titles(page)
    for title in reversed(titles):
        if title in DIRECT_GROUP_PAGES:
            return DIRECT_GROUP_PAGES[title]
        if title in SPECIALTY_GROUP_PAGES:
            return SPECIALTY_GROUP_PAGES[title]
    if any(title in NATURAL_ROOT_PAGES for title in titles):
        return "自然群"
    subject_group = infer_group_from_subject(page.get("courseName", ""))
    if subject_group:
        return subject_group
    return ""


def infer_group_from_subject(subject: str) -> str:
    if re.search(r"情報|プログラミング|計算機|データ|アルゴリズム|Informatics|Programming|Computer|Data|Algorithm", subject, re.IGNORECASE):
        return "情報群"
    if re.search(r"英語|ドイツ語|フランス語|中国語|スペイン語|ロシア語|イタリア語|朝鮮語|語IA|語IB|語IIA|語IIB|English|Linguistics", subject, re.IGNORECASE):
        return "外国語群"
    if re.search(r"朝鮮|韓国|精神分析|西洋史|日本史|法|政治|経済|経営|会計|心理|教育|文|哲学|歴史|社会|倫理|宗教|芸術", subject):
        return "人社群"
    if re.search(r"数理論理|特殊相対論|数学|物理|化学|生物|地球|統計|解析|代数|幾何|微分|積分|力学|電磁|量子|熱|有機|無機|確率|Probability|Game Theory|Statistics|Mathematics", subject, re.IGNORECASE):
        return "自然群"
    return ""


def page_ancestry_titles(page: dict) -> list[str]:
    return [page.get("title", "")] + [title for title in page.get("parentChain", []) if title]


def build_exam(page: dict, file_item: dict, parsed: dict, group: str) -> dict:
    notes = [
        "京都大学",
        f"KU1025ページ: {page['title']}",
        f"KU1025 URL: {page['url']}",
        f"ファイル名: {file_item.get('name')}",
    ]
    if page.get("parentTitle"):
        notes.append(f"KU1025親ページ: {page['parentTitle']}")
    if parsed.get("pageNumber"):
        notes.append(f"ページ分割ファイル: {parsed['pageNumber']}ページ目")
    exam = {
        "id": f"ku1025-{file_item['id']}" + (f"-{parsed['idSuffix']}" if parsed.get("idSuffix") else ""),
        "year": parsed["year"],
        "teacher": parsed["teacher"],
        "subject": parsed["subject"],
        "group": group,
        "testType": parsed.get("testType", "定期テスト"),
        "sourceSite": "KU1025",
        "localFile": "未保存",
        "driveUrl": file_item["url"],
        "notes": " / ".join(notes),
    }
    if parsed.get("pageGroup"):
        exam["pageGroup"] = "ku1025-" + safe_id_part(parsed["pageGroup"])
        exam["pageNumber"] = parsed["pageNumber"]
    return exam


def parse_ku1025_filename(filename: str, course_name: str) -> dict | list[dict] | None:
    parsed = parse_ku1025_annotated_filename(filename, course_name)
    if parsed:
        return parsed
    parsed = parse_exam_filename(filename, course_name)
    if parsed:
        return parsed
    path = Path(filename)
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        return None
    stem = path.with_suffix("").name.strip()
    page_match = re.search(r"[（(](\d{1,2})[）)]$", stem)
    if page_match:
        stem = stem[: page_match.start()].strip()
    year_match = re.search(r"((?:19|20)\d{2})(?:年度)?$", stem)
    if not year_match:
        return None
    before_year = stem[: year_match.start()].strip()
    subject = course_name.strip()
    teacher = ""
    paren_match = re.search(r"[（(]([^（）()]*)[）)]\s*$", before_year)
    if paren_match:
        teacher = normalize_teacher(paren_match.group(1))
        subject_from_file = before_year[: paren_match.start()].strip()
        if subject_from_file:
            subject = subject_from_file
    return {
        "year": year_match.group(1),
        "teacher": teacher,
        "subject": subject,
        "testType": infer_test_type(stem) or "定期テスト",
    }


def parse_ku1025_annotated_filename(filename: str, course_name: str) -> dict | None:
    path = Path(filename)
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        return None
    stem = path.with_suffix("").name.strip()
    match = re.fullmatch(r"(.+)[（(](.+)[）)]((?:19|20)\d{2})(?:年度)?[（(]([^（）()]*)[）)]", stem)
    if not match:
        return None
    annotation = match.group(4).strip()
    if annotation not in ("概要のみ", "問題のみ", "解答のみ"):
        return None
    subject = match.group(1).strip() or course_name.strip()
    teacher = normalize_teacher(match.group(2))
    year = match.group(3) + infer_term_from_subject(subject)
    return {
        "year": year,
        "teacher": teacher,
        "subject": subject,
        "testType": infer_test_type(stem) or "定期テスト",
    }


def clear_ku1025_paged_file_parses(files: list[dict], course_name: str) -> dict[str, dict]:
    candidates = []
    for file_item in files:
        path = Path(file_item["name"])
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        match = re.search(r"^(?P<base>.+(?:19|20)\d{2})(?:[（(](?P<page>\d{1,2})[）)])$", path.with_suffix("").name.strip())
        if not match:
            continue
        candidates.append({"file": file_item, "base": match.group("base"), "pageNumber": int(match.group("page"))})

    grouped = {}
    for candidate in candidates:
        grouped.setdefault(candidate["base"], []).append(candidate)

    parses = {}
    for base, group in grouped.items():
        pages = sorted(item["pageNumber"] for item in group)
        if len(group) < 2 or pages != list(range(1, len(group) + 1)):
            continue
        parsed = parse_ku1025_filename(base + ".pdf", course_name)
        if not parsed or isinstance(parsed, list):
            continue
        page_group = "ku1025-pagegroup-" + safe_id_part(course_name) + "-" + safe_id_part(base)
        for item in group:
            parses[item["file"]["id"]] = {**parsed, "pageGroup": page_group, "pageNumber": item["pageNumber"]}
    return parses


def report_page(page: dict) -> dict:
    return {
        "title": page.get("title", "未登録"),
        "parentTitle": page.get("parentTitle", ""),
        "url": page.get("url", ""),
    }


def report_file(file_item: dict) -> dict:
    return {
        "id": file_item.get("id"),
        "name": file_item.get("name"),
        "url": file_item.get("url"),
    }


def unresolved_items(page: dict, files: list[dict], reason: str) -> list[dict]:
    return [{"page": report_page(page), "file": report_file(file_item), "reason": reason} for file_item in files]


def discard_ku1025_records(exams: list[dict]) -> list[dict]:
    return [exam for exam in exams if not str(exam.get("id", "")).startswith("ku1025-")]


def unique_file_items(files: list[dict]) -> list[dict]:
    seen = set()
    result = []
    for file_item in files:
        key = (file_item.get("id"), file_item.get("pageUrl"))
        if key in seen:
            continue
        seen.add(key)
        result.append(file_item)
    return result


def curl_text(url: str) -> str:
    url = request_url(url)
    try:
        result = run(
            ["curl", "-LsA", USER_AGENT, "--connect-timeout", "10", "--max-time", "25", url],
            check=True,
            capture_output=True,
            text=True,
            timeout=35,
        )
    except TimeoutExpired as error:
        raise RuntimeError(f"KU1025ページの取得がタイムアウトしました: {url}") from error
    except CalledProcessError as error:
        raise RuntimeError(error.stderr.strip() or f"curl failed: {url}") from error
    return result.stdout


def request_url(url: str) -> str:
    parsed = urlparse(url)
    path = quote(unquote(parsed.path), safe="/%")
    return parsed._replace(path=path).geturl()


def read_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
