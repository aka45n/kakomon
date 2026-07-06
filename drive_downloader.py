from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, unquote, urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener
import json
import re


ROOT = Path(__file__).resolve().parent
DATA_PATH = ROOT / "data" / "exams.json"
FILES_DIR = ROOT / "files"


def download_exam_file(exam_id):
    if not exam_id:
        raise ValueError("過去問IDが指定されていません。")

    exams = read_exams()
    exam = next((item for item in exams if item.get("id") == exam_id), None)
    if not exam:
        raise ValueError("指定された過去問が見つかりません。")
    if not exam.get("driveUrl"):
        raise ValueError("Google Driveリンクが登録されていません。")

    try:
        drive_url = build_drive_download_url(exam["driveUrl"])
        opener = build_opener(HTTPCookieProcessor())
        response = open_drive_url(opener, drive_url)
        response = follow_drive_confirm_if_needed(opener, response)
        content = response.read()
    except (HTTPError, URLError) as error:
        raise ValueError(f"Driveから取得できませんでした: {error}") from error

    if not content:
        raise ValueError("Driveから空のファイルが返されました。")

    filename = response_filename(response) or default_filename(exam)
    target = unique_target_path(FILES_DIR / safe_path_part(filename))
    FILES_DIR.mkdir(exist_ok=True)
    target.write_bytes(content)

    exam["localFile"] = f"./files/{target.name}"
    DATA_PATH.write_text(json.dumps(exams, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"localFile": exam["localFile"]}


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


def default_filename(exam):
    parts = [exam.get("year"), exam.get("subject"), exam.get("teacher"), exam.get("group"), exam.get("testType")]
    stem = "_".join(safe_path_part(part) for part in parts if part)
    return f"{stem or exam['id']}.pdf"


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
