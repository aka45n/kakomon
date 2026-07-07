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
CA_BUNDLE_CANDIDATES = (
    Path("/etc/ssl/cert.pem"),
    Path("/opt/homebrew/etc/ca-certificates/cert.pem"),
    Path("/usr/local/etc/openssl@3/cert.pem"),
)


def download_exam_file(exam_id):
    if not exam_id:
        raise ValueError("過去問IDが指定されていません。")

    exams = read_exams()
    exam = next((item for item in exams if item.get("id") == exam_id), None)
    if not exam:
        raise ValueError("指定された過去問が見つかりません。")
    if not exam.get("driveUrl"):
        raise ValueError("Google Driveリンクが登録されていません。")

    if exam.get("pageGroup"):
        return download_page_group(exams, exam)

    content, filename = download_drive_content(exam["driveUrl"])
    target = unique_target_path(FILES_DIR / exam_filename(exam, suffix=downloaded_suffix(filename, exam)))
    FILES_DIR.mkdir(exist_ok=True)
    target.write_bytes(content)

    exam["localFile"] = f"./files/{target.name}"
    DATA_PATH.write_text(json.dumps(exams, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"localFile": exam["localFile"]}


def download_page_group(exams, exam):
    page_group = exam["pageGroup"]
    pages = [item for item in exams if item.get("pageGroup") == page_group and item.get("driveUrl")]
    pages.sort(key=lambda item: (int(item.get("pageNumber") or 0), item.get("id", "")))
    if not pages:
        raise ValueError("ページ結合対象が見つかりません。")

    FILES_DIR.mkdir(exist_ok=True)
    target = unique_target_path(FILES_DIR / exam_filename(exam, suffix=".pdf"))

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

    local_file = f"./files/{target.name}"
    for page in pages:
        page["localFile"] = local_file
    DATA_PATH.write_text(json.dumps(exams, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"localFile": local_file}


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
            sys.path.append(str(bundled_python_packages))
            from pypdf import PdfReader, PdfWriter

            return PdfReader, PdfWriter
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
    subject = safe_filename_text(exam.get("subject") or exam.get("id") or "過去問")
    teacher = safe_filename_text(clean_teacher_name(exam.get("teacher", "")))
    year = safe_filename_text(exam.get("year", ""))
    return f"{subject}({teacher}){year}{suffix.lower()}"


def clean_teacher_name(value):
    return re.sub(r"\s+", "", str(value))


def downloaded_suffix(filename, exam):
    suffix = Path(filename or "").suffix.lower()
    if suffix:
        return suffix
    suffix = suffix_from_url(exam.get("driveUrl", ""))
    return suffix or ".pdf"


def safe_filename_text(value):
    value = str(value).strip()
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
