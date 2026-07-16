from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, unquote, urlparse
from urllib.request import HTTPSHandler, HTTPCookieProcessor, Request, build_opener
import json
import os
import re
import ssl
import sys
import tempfile


ROOT = Path(os.environ.get("KAKOMON_ROOT", Path(__file__).resolve().parent))
DATA_PATH = ROOT / "data" / "exams.json"
FILES_DIR = ROOT / "files"
DRIVE_FILES_DIR = FILES_DIR / "drive"
SEED_ROOT = Path(os.environ["KAKOMON_SEED_ROOT"]) if os.environ.get("KAKOMON_SEED_ROOT") else None
DASH_VARIANTS = str.maketrans({
    "‐": "－",
    "‑": "－",
    "‒": "－",
    "–": "－",
    "—": "－",
    "―": "－",
    "−": "－",
})
CA_BUNDLE_CANDIDATES = (
    Path("/etc/ssl/cert.pem"),
    Path("/opt/homebrew/etc/ca-certificates/cert.pem"),
    Path("/usr/local/etc/openssl@3/cert.pem"),
)


def download_exam_file(exam_id, year_page_map=None):
    if not exam_id:
        raise ValueError("過去問IDが指定されていません。")

    exams = read_exams()
    exam = next((item for item in exams if item.get("id") == exam_id), None)
    if not exam:
        raise ValueError("指定された過去問が見つかりません。")
    if is_multi_year_source(exam):
        if not year_page_map:
            raise ValueError("年度ごとのページ割り当てが指定されていません。")
        return download_multi_year_exam(exams, exam, year_page_map)
    existing_local_file = existing_local_file_path(exam)
    if existing_local_file:
        return {"localFile": exam["localFile"], "alreadyDownloaded": True}
    if exam.get("sourceSite") == "手動追加" or str(exam.get("id", "")).startswith("manual-"):
        raise ValueError("手動追加の過去問はDriveから保存できません。")
    if not exam.get("driveUrl"):
        raise ValueError("Google Driveリンクが登録されていません。")

    if exam.get("pageGroup"):
        return download_page_group(exams, exam)

    content, filename = download_drive_content(exam["driveUrl"])
    target = unique_target_path(DRIVE_FILES_DIR / exam_filename(exam, suffix=downloaded_suffix(filename, exam)))
    DRIVE_FILES_DIR.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)

    exam["localFile"] = f"./files/drive/{target.name}"
    write_exams(exams)
    return {"localFile": exam["localFile"]}


def is_multi_year_source(exam):
    return len(exam.get("alternateYears") or []) > 1 and bool(
        re.match(r"^\d{4}\s*(?:-|－|〜|～)\s*\d{4}", normalize_hyphens(exam.get("year", "")))
    )


def download_multi_year_exam(exams, exam, year_page_map):
    allowed_years = [str(year).strip() for year in exam.get("alternateYears") or [] if str(year).strip()]
    downloaded_years = {
        item.get("year")
        for item in exams
        if item.get("derivedFromExamId") == exam.get("id") and existing_local_file_path(item)
    }
    normalized_map = {}
    used_pages = set()
    for year, pages in year_page_map.items():
        if year not in allowed_years:
            raise ValueError(f"対象外の年度が指定されています: {year}")
        if year in downloaded_years:
            raise ValueError(f"{year}はすでに保存済みです。")
        normalized_pages = sorted({int(page) for page in pages})
        if not normalized_pages or normalized_pages[0] < 1:
            raise ValueError(f"{year}のページ番号が正しくありません。")
        duplicates = used_pages.intersection(normalized_pages)
        if duplicates:
            page_text = ", ".join(str(page) for page in sorted(duplicates))
            raise ValueError(f"同じページが複数年度に指定されています: {page_text}")
        used_pages.update(normalized_pages)
        normalized_map[year] = normalized_pages

    content, filename = download_drive_content(exam["driveUrl"])
    suffix = downloaded_suffix(filename, exam)
    if suffix != ".pdf":
        raise ValueError("複数年度資料の年度別保存はPDFにのみ対応しています。")

    PdfReader, PdfWriter = import_pypdf()
    DRIVE_FILES_DIR.mkdir(parents=True, exist_ok=True)
    created_paths = []
    created_records = []
    with tempfile.TemporaryDirectory() as tmpdir:
        source_path = Path(tmpdir) / "source.pdf"
        source_path.write_bytes(content)
        reader = PdfReader(str(source_path))
        page_count = len(reader.pages)
        invalid_pages = sorted(page for page in used_pages if page > page_count)
        if invalid_pages:
            page_text = ", ".join(str(page) for page in invalid_pages)
            raise ValueError(f"PDFは{page_count}ページです。範囲外の指定があります: {page_text}")

        try:
            for year, pages in normalized_map.items():
                record = build_year_exam_record(exam, year, pages)
                target = unique_target_path(DRIVE_FILES_DIR / exam_filename(record, suffix=".pdf"))
                writer = PdfWriter()
                for page_number in pages:
                    writer.add_page(reader.pages[page_number - 1])
                with target.open("wb") as output:
                    writer.write(output)
                record["localFile"] = f"./files/drive/{target.name}"
                created_paths.append(target)
                created_records.append(record)
        except Exception:
            for path in created_paths:
                path.unlink(missing_ok=True)
            raise

    for record in created_records:
        existing = next((item for item in exams if item.get("id") == record["id"]), None)
        if existing:
            existing.update(record)
        else:
            exams.append(record)
    write_exams(exams)
    local_files = [record["localFile"] for record in created_records]
    return {
        "localFile": local_files[0],
        "localFiles": local_files,
        "createdExamIds": [record["id"] for record in created_records],
    }


def build_year_exam_record(source_exam, year, pages):
    record = dict(source_exam)
    record["id"] = f"{source_exam['id']}-year-{safe_path_part(year)}"
    record["year"] = year
    record["localFile"] = "未保存"
    record["derivedFromExamId"] = source_exam["id"]
    record["sourcePages"] = pages
    record.pop("alternateYears", None)
    record.pop("driveUrl", None)
    record.pop("pageGroup", None)
    record.pop("pageNumber", None)
    page_text = ",".join(str(page) for page in pages)
    note = f"複数年度資料から年度別に保存（元ID: {source_exam['id']} / ページ: {page_text}）"
    record["notes"] = f"{source_exam.get('notes', '').rstrip()} / {note}".lstrip(" / ")
    return record


def existing_local_file_path(exam):
    local_file = exam.get("localFile")
    if local_file in ("", "未保存", None):
        return None
    path = Path(local_file)
    path = path if path.is_absolute() else ROOT / path
    return path if path.exists() else None


def download_page_group(exams, exam):
    page_group = exam["pageGroup"]
    pages = [item for item in exams if item.get("pageGroup") == page_group and item.get("driveUrl")]
    pages.sort(key=lambda item: (int(item.get("pageNumber") or 0), item.get("id", "")))
    if not pages:
        raise ValueError("ページ結合対象が見つかりません。")

    DRIVE_FILES_DIR.mkdir(parents=True, exist_ok=True)
    target = unique_target_path(DRIVE_FILES_DIR / exam_filename(exam, suffix=".pdf"))

    with tempfile.TemporaryDirectory() as tmpdir:
        page_paths = []
        for index, page in enumerate(pages, start=1):
            content, filename = download_drive_content(page["driveUrl"])
            suffix = Path(filename or "").suffix.lower()
            if not suffix:
                suffix = suffix_from_url(page.get("driveUrl", "")) or ".bin"
            page_path = Path(tmpdir) / f"page-{index}{suffix}"
            page_path.write_bytes(content)
            page_paths.append(page_path)
        combine_page_files(page_paths, target)

    local_file = f"./files/drive/{target.name}"
    for page in pages:
        page["localFile"] = local_file
    write_exams(exams)
    return {"localFile": local_file}


def mirror_data_paths():
    paths = []
    if SEED_ROOT:
        paths.append(SEED_ROOT / "data" / "exams.json")
        try:
            repo_root = SEED_ROOT.parents[2]
        except IndexError:
            repo_root = None
        if repo_root:
            paths.append(repo_root / "data" / "exams.json")

    unique = []
    seen = {DATA_PATH.resolve()}
    for path in paths:
        resolved = path.resolve()
        if resolved in seen:
            continue
        if path.exists() or (path.parent.exists() and (path.parent.parent / ".git").exists()):
            unique.append(path)
            seen.add(resolved)
    return unique


def write_exams(exams):
    text = json.dumps(exams, ensure_ascii=False, indent=2) + "\n"
    DATA_PATH.write_text(text, encoding="utf-8")
    for path in mirror_data_paths():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def combine_page_files(page_paths, target):
    suffixes = [path.suffix.lower() for path in page_paths]
    if all(suffix in (".jpg", ".jpeg", ".png", ".gif", ".tif", ".tiff") for suffix in suffixes):
        save_images_as_pdf(page_paths, target)
        return

    pdf_paths = []
    for path in page_paths:
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            pdf_paths.append(path)
        elif suffix in (".jpg", ".jpeg", ".png", ".gif", ".tif", ".tiff"):
            image_pdf_path = path.with_suffix(".pdf")
            save_images_as_pdf([path], image_pdf_path)
            pdf_paths.append(image_pdf_path)
        else:
            raise ValueError(f"PDF結合に対応していないファイル形式です: {suffix or '不明'}")
    merge_pdfs(pdf_paths, target)


def save_images_as_pdf(image_paths, target):
    from PIL import Image

    images = []
    try:
        for path in image_paths:
            images.append(Image.open(path).convert("RGB"))
        if not images:
            raise ValueError("PDF化するページ画像がありません。")
        images[0].save(target, save_all=True, append_images=images[1:])
    finally:
        for image in images:
            image.close()


def merge_pdfs(pdf_paths, target):
    PdfReader, PdfWriter = import_pypdf()
    writer = PdfWriter()
    for path in pdf_paths:
        reader = PdfReader(str(path))
        for page in reader.pages:
            writer.add_page(page)
    with target.open("wb") as output:
        writer.write(output)


def import_pypdf():
    try:
        from pypdf import PdfReader, PdfWriter

        return PdfReader, PdfWriter
    except ModuleNotFoundError:
        bundled_python_packages = Path.home() / ".cache" / "codex-runtimes" / "codex-primary-runtime" / "dependencies" / "python"
        if bundled_python_packages.exists():
            for site_packages in bundled_python_packages.glob("lib/python*/site-packages"):
                if str(site_packages) not in sys.path:
                    sys.path.append(str(site_packages))
            try:
                from pypdf import PdfReader, PdfWriter

                return PdfReader, PdfWriter
            except ModuleNotFoundError:
                pass
        raise ValueError("PDFページの結合には pypdf が必要です。") from None


def suffix_from_url(url):
    suffix = Path(urlparse(url).path).suffix.lower()
    return suffix if suffix else ""


def download_drive_content(drive_url):
    try:
        drive_url = build_drive_download_url(drive_url)
        opener = build_drive_opener()
        response = open_drive_url(opener, drive_url)
        response = follow_drive_confirm_if_needed(opener, response)
        content = response.read()
    except (HTTPError, URLError) as error:
        raise ValueError(f"Driveから取得できませんでした: {error}") from error

    if not content:
        raise ValueError("Driveから空のファイルが返されました。")
    return content, response_filename(response)


def build_drive_opener():
    context = ssl.create_default_context(cafile=ca_bundle_path())
    return build_opener(HTTPCookieProcessor(), HTTPSHandler(context=context))


def ca_bundle_path():
    for candidate in CA_BUNDLE_CANDIDATES:
        if candidate.exists():
            return str(candidate)
    return None


def read_exams():
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def build_drive_download_url(url):
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    if "id" in query:
        return f"https://drive.google.com/uc?export=download&id={query['id'][0]}"

    match = re.search(r"/file/d/([^/]+)", parsed.path)
    if match:
        return f"https://drive.google.com/uc?export=download&id={match.group(1)}"

    return url


def open_drive_url(opener, url):
    request = Request(url, headers={"User-Agent": "kakomon-local-downloader/1.0"})
    return opener.open(request, timeout=60)


def follow_drive_confirm_if_needed(opener, response):
    content_type = response.headers.get("Content-Type", "")
    if "text/html" not in content_type:
        return response

    html = response.read().decode("utf-8", errors="ignore")
    confirm_url = extract_confirm_url(html)
    if not confirm_url:
        raise ValueError("Driveの確認画面または認証画面が返されました。共有設定を確認してください。")
    return open_drive_url(opener, confirm_url)


def extract_confirm_url(html):
    match = re.search(r'href="([^"]*confirm=[^"]*)"', html)
    if not match:
        return None
    return "https://drive.google.com" + unquote(match.group(1).replace("&amp;", "&"))


def response_filename(response):
    disposition = response.headers.get("Content-Disposition", "")
    match = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)', disposition)
    if match:
        return unquote(match.group(1))
    return None


def exam_filename(exam, suffix=None):
    suffix = suffix or ".pdf"
    if not suffix.startswith("."):
        suffix = f".{suffix}"
    source_site = safe_filename_text(source_site_filename_label(exam.get("sourceSite", "")))
    subject = safe_filename_text(exam.get("subject") or exam.get("id") or "過去問")
    teacher = safe_filename_text(clean_teacher_name(exam.get("teacher", "")))
    year = safe_filename_text(exam.get("year", ""))
    test_type = safe_filename_text(test_type_filename_label(exam))
    test_part = f"_{test_type}" if test_type else ""
    source_part = f"_{source_site}" if source_site else ""
    return f"{subject}({teacher}){year}{test_part}{source_part}{suffix.lower()}"


def source_site_filename_label(source_site):
    labels = {
        "京大wiki": "KUwiki",
        "KU1025": "KU1025",
    }
    return labels.get(str(source_site).strip(), source_site)


def test_type_filename_label(exam):
    test_type = str(exam.get("testType") or "").strip()
    if test_type == "小テスト" and exam.get("testNumber"):
        return f"小テスト{exam.get('testNumber')}"
    return test_type


def clean_teacher_name(value):
    return re.sub(r"\s+", "", normalize_teacher_separators(value))


def normalize_hyphens(value):
    return str(value).translate(DASH_VARIANTS)


def normalize_teacher_separators(value):
    value = normalize_hyphens(value)
    return re.sub(r"\s*[･、，,／/&＆]\s*", "・", value)


def downloaded_suffix(filename, exam):
    suffix = Path(filename or "").suffix.lower()
    if suffix:
        return suffix
    suffix = suffix_from_url(exam.get("driveUrl", ""))
    return suffix or ".pdf"


def safe_filename_text(value):
    value = normalize_hyphens(value).strip()
    value = value.replace("/", "_").replace(":", "_")
    value = re.sub(r"[\x00-\x1f]", "", value)
    value = re.sub(r"\s+", "", value)
    return value or ""


def safe_path_part(value):
    value = str(value).strip().replace("/", "_")
    value = re.sub(r"[^0-9A-Za-z一-龥ぁ-んァ-ヶー々〆〤._-]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("._")
    return value or "file"


def unique_target_path(path):
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for index in range(2, 1000):
        candidate = path.with_name(f"{stem}-{index}{suffix}")
        if not candidate.exists():
            return candidate
    raise ValueError("保存先ファイル名を決定できませんでした。")
