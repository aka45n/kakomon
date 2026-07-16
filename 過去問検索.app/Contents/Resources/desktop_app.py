from pathlib import Path
from datetime import datetime
import shutil
import json
import os
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import webbrowser

from drive_downloader import DATA_PATH, FILES_DIR, ROOT, download_exam_file, write_exams


FEEDBACK_PATH = ROOT / "data" / "feedback.json"
EDIT_HISTORY_PATH = ROOT / "data" / "edit_history.json"
MANUAL_FILES_DIR = FILES_DIR / "manual"
DRIVE_FILES_DIR = FILES_DIR / "drive"
SEED_ROOT = Path(os.environ["KAKOMON_SEED_ROOT"]) if os.environ.get("KAKOMON_SEED_ROOT") else None
EDIT_HISTORY_LIMIT = 30
TEST_TYPES = ("小テスト", "定期テスト")
TERMS = ("前期", "後期")
COURSE_GROUPS = (
    "人社群",
    "自然群",
    "外国語群",
    "情報群",
    "健康群",
    "キャリア形成科目群",
    "統合科学科目群",
    "少人数教育科目群",
    "工学部専門科目",
    "理学部専門科目",
    "法学部専門科目",
    "農学部専門科目",
    "総合人間学部専門科目",
    "大学院科目",
)
SORT_LABELS = {
    "year_desc": "年度が新しい順",
    "year_asc": "年度が古い順",
    "subject_asc": "科目名 昇順",
    "subject_desc": "科目名 降順",
    "teacher_asc": "教師名 昇順",
    "teacher_desc": "教師名 降順",
    "group_asc": "群 昇順",
    "group_desc": "群 降順",
    "test_type_asc": "種別 昇順",
    "test_type_desc": "種別 降順",
    "source_site_asc": "取得元 昇順",
    "source_site_desc": "取得元 降順",
}
SORT_COLUMNS = {
    "year": ("year_asc", "year_desc"),
    "subject": ("subject_asc", "subject_desc"),
    "teacher": ("teacher_asc", "teacher_desc"),
    "group": ("group_asc", "group_desc"),
    "test_type": ("test_type_asc", "test_type_desc"),
    "source_site": ("source_site_asc", "source_site_desc"),
}
MISSING_LOCAL_FILE_VALUES = ("", "未保存", None)
DASH_VARIANTS = str.maketrans({
    "‐": "－",
    "‑": "－",
    "‒": "－",
    "–": "－",
    "—": "－",
    "―": "－",
    "−": "－",
})
INPUT_SOURCE_SWITCH_KEYS = {
    "Alt_L",
    "Alt_R",
    "Caps_Lock",
    "Command_L",
    "Command_R",
    "Control_L",
    "Control_R",
    "ISO_Next_Group",
    "Meta_L",
    "Meta_R",
    "Mode_switch",
    "Option_L",
    "Option_R",
    "Super_L",
    "Super_R",
}
INPUT_SOURCE_SPACE_GUARD_SECONDS = 0.5


def year_sort_value(value):
    match = re.match(r"^(\d{4})(前期|後期)?$", str(value))
    if not match:
        return (0, 0)
    semester_order = {"前期": 1, "後期": 2}
    return (int(match.group(1)), semester_order.get(match.group(2), 0))


def reverse_year_sort_value(value):
    year, semester = year_sort_value(value)
    return (-year, -semester)


def split_year_term(value):
    match = re.match(r"^(20\d{2})(前期|後期)$", str(value))
    if match:
        return match.group(1), match.group(2)
    match = re.match(r"^(20\d{2})$", str(value))
    if match:
        return match.group(1), ""
    return "20", ""


def normalize_group(value):
    return value


def normalize_hyphens(value):
    return str(value).translate(DASH_VARIANTS)


def normalize_teacher_separators(value):
    value = normalize_hyphens(value)
    return re.sub(r"\s*[･、，,／/&＆]\s*", "・", value)


def has_local_file(exam):
    return exam.get("localFile") not in MISSING_LOCAL_FILE_VALUES


def local_file_path(exam):
    path = exam.get("localFile")
    if not has_local_file(exam):
        return None
    return (ROOT / path).resolve() if not Path(path).is_absolute() else Path(path)


def local_file_exists(exam):
    path = local_file_path(exam)
    return bool(path and path.exists())


def safe_filename_part(value):
    value = str(value).strip().replace("/", "_")
    value = re.sub(r"[^0-9A-Za-z一-龥ぁ-んァ-ヶー々〆〤._-]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("._")
    return value or "file"


def safe_rule_filename_text(value):
    value = normalize_hyphens(value).strip()
    value = value.replace("/", "_").replace(":", "_")
    value = re.sub(r"[\x00-\x1f]", "", value)
    value = re.sub(r"\s+", "", value)
    return value


def clean_teacher_name(value):
    return re.sub(r"\s+", "", normalize_teacher_separators(value))


def exam_rule_filename(subject, teacher, year, suffix, test_type="", test_number=""):
    suffix = suffix or ".pdf"
    if not suffix.startswith("."):
        suffix = f".{suffix}"
    subject = safe_rule_filename_text(subject) or "過去問"
    teacher = safe_rule_filename_text(clean_teacher_name(teacher))
    year = safe_rule_filename_text(year)
    number_part = ""
    if test_type == "小テスト" and test_number:
        number_part = f"_小テスト{safe_rule_filename_text(test_number)}"
    return f"{subject}({teacher}){year}{number_part}{suffix.lower()}"


def downloaded_rule_filename(subject, teacher, year, suffix, test_type="", test_number="", source_site=""):
    suffix = suffix or ".pdf"
    if not suffix.startswith("."):
        suffix = f".{suffix}"
    subject = safe_rule_filename_text(subject) or "過去問"
    teacher = safe_rule_filename_text(clean_teacher_name(teacher))
    year = safe_rule_filename_text(year)
    test_label = safe_rule_filename_text(test_type_filename_label(test_type, test_number))
    source_label = safe_rule_filename_text(source_site_filename_label(source_site))
    test_part = f"_{test_label}" if test_label else ""
    source_part = f"_{source_label}" if source_label else ""
    return f"{subject}({teacher}){year}{test_part}{source_part}{suffix.lower()}"


def source_site_filename_label(source_site):
    labels = {
        "京大wiki": "KUwiki",
        "KU1025": "KU1025",
    }
    return labels.get(str(source_site).strip(), source_site)


def test_type_filename_label(test_type, test_number=""):
    test_type = str(test_type or "").strip()
    if test_type == "小テスト" and test_number:
        return f"小テスト{test_number}"
    return test_type


def exam_test_types(exam):
    types = []
    for test_type in [exam.get("testType", ""), *(exam.get("alternateTestTypes") or [])]:
        if test_type in TEST_TYPES and test_type not in types:
            types.append(test_type)
    return types or [exam.get("testType", "")]


def exam_years(exam):
    years = []
    for year in [exam.get("year", ""), *(exam.get("alternateYears") or [])]:
        year = str(year or "").strip()
        if year and year not in years:
            years.append(year)
    return years or [exam.get("year", "")]


def latest_exam_year(exam):
    valid_years = [year for year in exam_years(exam) if year_sort_value(year) != (0, 0)]
    if not valid_years:
        return exam.get("year", "")
    return max(valid_years, key=year_sort_value)


def latest_year_sort_value(exam):
    return year_sort_value(latest_exam_year(exam))


def reverse_latest_year_sort_value(exam):
    return reverse_year_sort_value(latest_exam_year(exam))


def display_year(exam, alternate_index=0):
    years = exam_years(exam)
    return years[alternate_index % len(years)]


def display_test_type(exam, alternate_index=0):
    test_types = exam_test_types(exam)
    test_type = test_types[alternate_index % len(test_types)]
    test_number = exam.get("testNumber")
    if test_type == "小テスト" and test_number:
        return f"小テスト{test_number}"
    return test_type


def test_order_value(exam):
    if exam.get("testType") == "小テスト":
        number = exam.get("testNumber")
        if number in ("", None):
            return (0, 0)
        try:
            return (0, int(number))
        except (TypeError, ValueError):
            return (0, 9999)
    if exam.get("testType") == "定期テスト":
        return (1, 0)
    return (2, 0)


def same_exam_condition_key(exam):
    return (
        exam.get("year", ""),
        exam.get("teacher", ""),
        exam.get("subject", ""),
        normalize_group(exam.get("group", "")),
    )


def unique_file_path(path):
    if not path.exists():
        return path
    for index in range(2, 1000):
        candidate = path.with_name(f"{path.stem}-{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise ValueError("保存先ファイル名を決定できませんでした。")


class KakomonApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("過去問検索")
        self.geometry("1120x700")
        self.minsize(900, 560)

        self.exams = []
        self.feedback = []
        self.filtered = []
        self.has_searched = False
        self.subject_query_var = tk.StringVar()
        self.teacher_query_var = tk.StringVar()
        self.year_var = tk.StringVar()
        self.group_var = tk.StringVar()
        self.test_type_var = tk.StringVar()
        self.source_site_filter_var = tk.StringVar()
        self.sort_var = tk.StringVar(value="year_desc")
        self.status_var = tk.StringVar(value="準備中")
        self.local_file_var = tk.StringVar(value="ローカルファイル: 未選択")
        self.source_site_var = tk.StringVar(value="取得元: 未選択")
        self.notes_var = tk.StringVar(value="注釈: 未選択")
        self.feedback_summary_var = tk.StringVar(value="メモ: 未選択")
        self.tree_headings = {}
        self.test_type_display_tick = 0
        self.download_active = False
        self.input_source_space_guard_until = 0.0
        self.input_source_space_guard_pending = False

        self.ensure_data_store()
        self.create_widgets()
        self.create_context_menu()
        self.load_data()
        self.bind_events()
        self.clear_results("検索条件を指定して検索してください")
        self.focus_landing_search()
        self.schedule_test_type_display_refresh()

    def ensure_data_store(self):
        (ROOT / "data").mkdir(parents=True, exist_ok=True)
        FILES_DIR.mkdir(parents=True, exist_ok=True)
        MANUAL_FILES_DIR.mkdir(parents=True, exist_ok=True)
        DRIVE_FILES_DIR.mkdir(parents=True, exist_ok=True)

        seed_data_dir = SEED_ROOT / "data" if SEED_ROOT else None
        for name, default_content in (
            ("exams.json", "[]\n"),
            ("feedback.json", "[]\n"),
            ("edit_history.json", "[]\n"),
        ):
            target = ROOT / "data" / name
            if target.exists():
                continue
            seed = seed_data_dir / name if seed_data_dir else None
            if seed and seed.exists():
                shutil.copyfile(seed, target)
            else:
                target.write_text(default_content, encoding="utf-8")
        self.merge_seed_exams()

    def mirror_root_candidates(self):
        if not SEED_ROOT:
            return []
        candidates = [SEED_ROOT]
        try:
            candidates.append(SEED_ROOT.parents[2])
        except IndexError:
            pass

        unique = []
        seen = {ROOT.resolve()}
        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved in seen:
                continue
            if (candidate / "data").exists() or (candidate / "過去問検索.app" / "Contents" / "Resources").exists():
                unique.append(candidate)
                seen.add(resolved)
        return unique

    def mirror_manual_file(self, local_file):
        if (
            not local_file
            or not str(local_file).startswith("./files/")
            or str(local_file).startswith("./files/drive/")
        ):
            return
        source = (ROOT / local_file).resolve()
        if not source.exists():
            return
        relative = Path(local_file[2:])
        for mirror_root in self.mirror_root_candidates():
            target = mirror_root / relative
            if target.resolve() == source:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)

    def remove_mirrored_manual_file(self, local_file):
        if (
            not local_file
            or not str(local_file).startswith("./files/")
            or str(local_file).startswith("./files/drive/")
        ):
            return
        relative = Path(str(local_file)[2:])
        for mirror_root in self.mirror_root_candidates():
            target = mirror_root / relative
            if target.exists():
                target.unlink()

    def merge_seed_exams(self):
        if not SEED_ROOT:
            return
        seed_path = SEED_ROOT / "data" / "exams.json"
        target_path = ROOT / "data" / "exams.json"
        if not seed_path.exists() or not target_path.exists():
            return
        try:
            seed_exams = json.loads(seed_path.read_text(encoding="utf-8"))
            current_exams = json.loads(target_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return
        existing_ids = {exam.get("id") for exam in current_exams}
        missing = [exam for exam in seed_exams if exam.get("id") and exam.get("id") not in existing_ids]
        if not missing:
            return
        current_exams.extend(missing)
        current_exams.sort(key=lambda item: (item.get("subject", ""), item.get("year", ""), item.get("teacher", ""), item.get("id", "")))
        write_exams(current_exams)

    def create_widgets(self):
        self.columnconfigure(0, weight=0)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        self.landing_frame = ttk.Frame(self, padding=32)
        self.landing_frame.grid(row=0, column=0, columnspan=2, sticky="nsew")
        self.landing_frame.columnconfigure(0, weight=1)
        self.landing_frame.rowconfigure(0, weight=0)
        self.landing_frame.rowconfigure(1, weight=1)

        landing_header = ttk.Frame(self.landing_frame)
        landing_header.grid(row=0, column=0, sticky="ew")
        landing_header.columnconfigure(0, weight=1)
        ttk.Button(landing_header, text="過去問を追加", command=self.open_add_exam_dialog).grid(row=0, column=1, sticky="e")

        landing_panel = ttk.Frame(self.landing_frame, padding=24)
        landing_panel.grid(row=1, column=0)
        landing_panel.columnconfigure(0, weight=1)
        landing_panel.columnconfigure(1, weight=1)

        ttk.Label(landing_panel, text="過去問検索", font=("", 28, "bold")).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(landing_panel, text="条件を1つ以上指定して検索").grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 18))

        self.landing_subject_entry = self.add_labeled_entry(landing_panel, "科目名", self.subject_query_var, 2)
        self.landing_teacher_entry = self.add_labeled_entry(landing_panel, "教師名", self.teacher_query_var, 4)
        self.landing_year_combo = self.add_labeled_combo(landing_panel, "年度", self.year_var, 6)
        self.landing_group_combo = self.add_labeled_combo(landing_panel, "科目群", self.group_var, 8)
        self.landing_test_type_combo = self.add_labeled_combo(landing_panel, "テスト種別", self.test_type_var, 10)
        self.landing_source_site_combo = self.add_labeled_combo(landing_panel, "取得元", self.source_site_filter_var, 12)

        landing_button_frame = ttk.Frame(landing_panel)
        landing_button_frame.grid(row=14, column=0, sticky="ew", pady=(18, 0))
        landing_button_frame.columnconfigure(0, weight=1)
        landing_button_frame.columnconfigure(1, weight=1)
        ttk.Button(landing_button_frame, text="検索", command=self.apply_filters).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(landing_button_frame, text="条件をクリア", command=self.reset_filters).grid(row=0, column=1, sticky="ew", padx=(6, 0))

        self.filter_frame = ttk.Frame(self, padding=16)
        self.filter_frame.grid(row=0, column=0, sticky="ns")
        self.filter_frame.columnconfigure(0, weight=1)

        ttk.Label(self.filter_frame, text="過去問検索", font=("", 22, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(self.filter_frame, text="条件を1つ以上指定して絞り込み").grid(row=1, column=0, sticky="w", pady=(4, 18))

        self.subject_entry = self.add_labeled_entry(self.filter_frame, "科目名", self.subject_query_var, 2)
        self.teacher_entry = self.add_labeled_entry(self.filter_frame, "教師名", self.teacher_query_var, 4)
        self.year_combo = self.add_labeled_combo(self.filter_frame, "年度", self.year_var, 6)
        self.group_combo = self.add_labeled_combo(self.filter_frame, "科目群", self.group_var, 8)
        self.test_type_combo = self.add_labeled_combo(self.filter_frame, "テスト種別", self.test_type_var, 10)
        self.source_site_combo = self.add_labeled_combo(self.filter_frame, "取得元", self.source_site_filter_var, 12)

        button_frame = ttk.Frame(self.filter_frame)
        button_frame.grid(row=14, column=0, sticky="ew", pady=(18, 0))
        button_frame.columnconfigure(0, weight=1)
        ttk.Button(button_frame, text="条件をクリア", command=self.reset_filters).grid(row=0, column=0, sticky="ew")

        self.main_frame = ttk.Frame(self, padding=(0, 16, 16, 16))
        self.main_frame.grid(row=0, column=1, sticky="nsew")
        self.main_frame.columnconfigure(0, weight=1)
        self.main_frame.rowconfigure(1, weight=1)

        toolbar = ttk.Frame(self.main_frame)
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        toolbar.columnconfigure(0, weight=1)

        self.count_label = ttk.Label(toolbar, text="0件", font=("", 16, "bold"))
        self.count_label.grid(row=0, column=0, sticky="w")
        self.bulk_download_button = ttk.Button(toolbar, text="検索結果を一括ダウンロード", command=self.download_filtered, state="disabled")
        self.bulk_download_button.grid(row=0, column=1, padx=(8, 8), sticky="e")
        ttk.Button(toolbar, text="ホームへ", command=self.show_home).grid(row=0, column=2, sticky="e")

        table_frame = ttk.Frame(self.main_frame)
        table_frame.grid(row=1, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)

        columns = ("year", "subject", "teacher", "group", "test_type", "source_site")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")
        self.tree_headings = {
            "year": "年度",
            "subject": "科目名",
            "teacher": "教師名",
            "group": "群",
            "test_type": "種別",
            "source_site": "取得元",
        }
        widths = {
            "year": 70,
            "subject": 150,
            "teacher": 130,
            "group": 80,
            "test_type": 95,
            "source_site": 110,
        }
        for column in columns:
            if column in SORT_COLUMNS:
                self.tree.heading(column, text=self.heading_text(column), command=lambda selected=column: self.sort_by_column(selected))
            else:
                self.tree.heading(column, text=self.tree_headings[column])
            self.tree.column(column, width=widths[column], minwidth=60, stretch=column == "subject")

        y_scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        x_scroll = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")

        footer_frame = ttk.Frame(self.main_frame)
        footer_frame.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        footer_frame.columnconfigure(5, weight=1)
        ttk.Button(footer_frame, text="開く", command=self.open_preferred).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(footer_frame, text="詳細を表示", command=self.open_detail_page).grid(row=0, column=1, padx=(0, 8))
        ttk.Button(footer_frame, text="編集", command=self.open_edit_exam_dialog).grid(row=0, column=2, padx=(0, 8))
        ttk.Button(footer_frame, text="ファイルの場所を開く", command=self.open_file_location).grid(row=0, column=3, padx=(0, 8))
        self.download_button = ttk.Button(footer_frame, text="Driveからローカル保存", command=self.download_selected, state="disabled")
        self.download_button.grid(row=0, column=4, padx=(0, 8))
        ttk.Label(footer_frame, textvariable=self.status_var).grid(row=0, column=5, sticky="e")
        self.show_landing_layout()

    def create_context_menu(self):
        self.context_menu = tk.Menu(self, tearoff=False)
        self.context_menu.add_command(label="開く", command=self.open_preferred)
        self.context_menu.add_command(label="詳細を表示", command=self.open_detail_page)
        self.context_menu.add_command(label="編集", command=self.open_edit_exam_dialog)
        self.context_menu.add_command(label="ファイルの場所を開く", command=self.open_file_location)

    def add_labeled_entry(self, parent, label, variable, row):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w")
        entry = ttk.Entry(parent, textvariable=variable, width=28)
        self.guard_input_source_switch_space(entry)
        entry.grid(row=row + 1, column=0, sticky="ew", pady=(4, 8))
        return entry

    def add_labeled_combo(self, parent, label, variable, row):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w")
        combo = ttk.Combobox(parent, textvariable=variable, state="readonly", width=26)
        combo.grid(row=row + 1, column=0, sticky="ew", pady=(4, 8))
        return combo

    def bind_events(self):
        self.bind_all("<ButtonPress-1>", self.focus_clicked_widget, add="+")
        self.tree.bind("<ButtonPress-1>", self.select_tree_row_on_click, add="+")
        self.tree.bind("<Double-1>", lambda _: self.open_preferred())
        self.tree.bind("<Button-2>", self.show_context_menu)
        self.tree.bind("<Button-3>", self.show_context_menu)
        self.tree.bind("<<TreeviewSelect>>", lambda _: self.update_selected_detail())
        self.bind_all("<KeyPress>", self.ignore_input_source_switch_space, add="+")
        self.landing_subject_entry.bind("<Return>", lambda _: self.apply_filters())
        self.landing_teacher_entry.bind("<Return>", lambda _: self.apply_filters())
        self.subject_query_var.trace_add("write", lambda *_: self.apply_filters_if_searched())
        self.teacher_query_var.trace_add("write", lambda *_: self.apply_filters_if_searched())
        for variable in (self.year_var, self.group_var, self.test_type_var, self.source_site_filter_var):
            variable.trace_add("write", lambda *_: self.apply_filters_if_searched())
        self.sort_var.trace_add("write", lambda *_: self.apply_filters())

    def heading_text(self, column):
        label = self.tree_headings.get(column, column)
        sort_key = self.sort_var.get()
        if sort_key == f"{column}_asc":
            return f"{label} ↑"
        if sort_key == f"{column}_desc":
            return f"{label} ↓"
        return label

    def update_heading_sort_indicators(self):
        for column in self.tree_headings:
            if column in SORT_COLUMNS:
                self.tree.heading(column, text=self.heading_text(column), command=lambda selected=column: self.sort_by_column(selected))
            else:
                self.tree.heading(column, text=self.tree_headings[column], command="")

    def sort_by_column(self, column):
        if column not in SORT_COLUMNS:
            return
        ascending, descending = SORT_COLUMNS[column]
        current = self.sort_var.get()
        if column == "year":
            next_sort = ascending if current == descending else descending
        else:
            next_sort = descending if current == ascending else ascending
        self.sort_var.set(next_sort)

    def focus_clicked_widget(self, event):
        try:
            event.widget.focus_set()
        except tk.TclError:
            pass

    def ignore_input_source_switch_space(self, event):
        # macOS can deliver the input-source shortcut's space after modifier
        # state has already disappeared. Arm a one-space guard on switch keys.
        now = time.monotonic()
        keysym = str(getattr(event, "keysym", ""))
        char = str(getattr(event, "char", ""))
        state = int(getattr(event, "state", 0) or 0)
        modifier_mask = 0x0004 | 0x0008 | 0x0010 | 0x0020 | 0x0040 | 0x0080

        if keysym in INPUT_SOURCE_SWITCH_KEYS:
            self.input_source_space_guard_pending = True
            self.input_source_space_guard_until = now + INPUT_SOURCE_SPACE_GUARD_SECONDS
            return None

        if keysym == "space" or char == " ":
            shortcut_space = bool(state & modifier_mask)
            delayed_switch_space = self.input_source_space_guard_pending and now <= self.input_source_space_guard_until
            if shortcut_space or delayed_switch_space:
                self.input_source_space_guard_pending = False
                return "break"
            return None

        if keysym:
            self.input_source_space_guard_pending = False
        return None

    def guard_input_source_switch_space(self, widget):
        widget.bind("<KeyPress>", self.ignore_input_source_switch_space, add="+")

    def select_tree_row_on_click(self, event):
        row_id = self.tree.identify_row(event.y)
        if not row_id:
            return
        self.tree.selection_set(row_id)
        self.tree.focus(row_id)
        self.update_selected_detail()

    def show_context_menu(self, event):
        row_id = self.tree.identify_row(event.y)
        if row_id:
            self.tree.selection_set(row_id)
            self.tree.focus(row_id)
            self.context_menu.tk_popup(event.x_root, event.y_root)
            self.context_menu.grab_release()

    def load_data(self):
        self.exams = json.loads(DATA_PATH.read_text(encoding="utf-8"))
        if self.normalize_exam_groups():
            write_exams(self.exams)
        self.feedback = self.read_feedback()
        self.refresh_filter_options()
        self.status_var.set("データを読み込みました")

    def normalize_exam_groups(self):
        changed = False
        for exam in self.exams:
            group = exam.get("group", "")
            normalized = normalize_group(group)
            if normalized != group:
                exam["group"] = normalized
                changed = True
        return changed

    def refresh_filter_options(self):
        years = [""] + sorted(self.unique_year_values(), key=year_sort_value, reverse=True)
        groups = [""] + list(COURSE_GROUPS)
        test_types = [""] + list(TEST_TYPES)
        source_sites = [""] + sorted(self.unique_values("sourceSite"))
        for combo in (self.year_combo, self.landing_year_combo):
            combo["values"] = years
        for combo in (self.group_combo, self.landing_group_combo):
            combo["values"] = groups
        for combo in (self.test_type_combo, self.landing_test_type_combo):
            combo["values"] = test_types
        for combo in (self.source_site_combo, self.landing_source_site_combo):
            combo["values"] = source_sites

    def unique_values(self, field):
        return {exam.get(field, "") for exam in self.exams if exam.get(field)}

    def unique_year_values(self):
        return {year for exam in self.exams for year in exam_years(exam) if year}

    def reset_filters(self):
        keep_results_layout = self.main_frame.winfo_ismapped()
        self.has_searched = False
        self.subject_query_var.set("")
        self.teacher_query_var.set("")
        self.year_var.set("")
        self.group_var.set("")
        self.test_type_var.set("")
        self.source_site_filter_var.set("")
        self.clear_results("検索条件を指定して検索してください")
        if keep_results_layout:
            self.show_results_layout()
            self.has_searched = True
            self.focus_widget(self.subject_entry)
        else:
            self.show_landing_layout()
            self.focus_landing_search()

    def show_home(self):
        self.has_searched = False
        self.show_landing_layout()
        self.clear_results("検索条件を指定して検索してください")
        self.focus_landing_search()

    def apply_filters(self):
        if not self.has_search_condition():
            self.clear_results("検索条件を1つ以上指定してください")
            if self.landing_frame.winfo_ismapped():
                self.focus_landing_search()
            else:
                self.focus_widget(self.subject_entry)
            return
        previous_focus = self.focus_get()
        self.has_searched = True
        self.show_results_layout()
        self.filtered = [
            exam
            for exam in self.exams
            if self.matches(exam)
        ]
        self.filtered = self.group_filtered_exams(self.filtered)
        self.sort_filtered()

        self.render_table()
        self.update_search_result_status()
        if not self.is_filter_focus(previous_focus):
            self.focus_results_table(select_first=True)

    def apply_filters_if_searched(self):
        if self.has_searched:
            self.apply_filters()

    def has_search_condition(self):
        return any((
            self.subject_query_var.get().strip(),
            self.teacher_query_var.get().strip(),
            self.year_var.get(),
            self.group_var.get(),
            self.test_type_var.get(),
            self.source_site_filter_var.get(),
        ))

    def clear_results(self, message):
        self.filtered = []
        self.tree.delete(*self.tree.get_children())
        self.count_label.config(text="0件")
        self.status_var.set(message)
        self.bulk_download_button.configure(state="disabled")
        self.update_selected_detail()

    def update_search_result_status(self):
        if self.filtered:
            self.status_var.set(f"検索結果: {len(self.filtered)}件")
        else:
            self.status_var.set("該当する過去問はありません")

    def show_landing_layout(self):
        self.filter_frame.grid_remove()
        self.main_frame.grid_remove()
        self.landing_frame.grid(row=0, column=0, columnspan=2, sticky="nsew")

    def show_results_layout(self):
        self.landing_frame.grid_remove()
        self.filter_frame.grid(row=0, column=0, sticky="ns")
        self.main_frame.grid(row=0, column=1, sticky="nsew")

    def matches(self, exam):
        subject_query = self.subject_query_var.get().strip().lower()
        teacher_query = self.teacher_query_var.get().strip().lower()
        if subject_query and subject_query not in str(exam.get("subject", "")).lower():
            return False
        if teacher_query and teacher_query not in str(exam.get("teacher", "")).lower():
            return False
        if self.year_var.get() and self.year_var.get() not in exam_years(exam):
            return False
        if self.group_var.get() and normalize_group(exam.get("group")) != self.group_var.get():
            return False
        if self.test_type_var.get() and self.test_type_var.get() not in exam_test_types(exam):
            return False
        if self.source_site_filter_var.get() and exam.get("sourceSite", "") != self.source_site_filter_var.get():
            return False
        return True

    def sort_key_newest(self, exam):
        return (reverse_latest_year_sort_value(exam), exam.get("subject", ""), exam.get("teacher", ""), normalize_group(exam.get("group", "")), test_order_value(exam))

    def sort_key_oldest(self, exam):
        return (latest_year_sort_value(exam), exam.get("subject", ""), exam.get("teacher", ""), normalize_group(exam.get("group", "")), test_order_value(exam))

    def sort_filtered(self):
        sort_key = self.sort_var.get()
        sorters = {
            "year_desc": (self.sort_key_newest, False),
            "year_asc": (self.sort_key_oldest, False),
            "subject_asc": (lambda exam: (exam.get("subject", ""), reverse_latest_year_sort_value(exam), same_exam_condition_key(exam), test_order_value(exam)), False),
            "subject_desc": (lambda exam: (exam.get("subject", ""), reverse_latest_year_sort_value(exam), same_exam_condition_key(exam), test_order_value(exam)), True),
            "teacher_asc": (lambda exam: (exam.get("teacher", ""), reverse_latest_year_sort_value(exam), same_exam_condition_key(exam), test_order_value(exam)), False),
            "teacher_desc": (lambda exam: (exam.get("teacher", ""), reverse_latest_year_sort_value(exam), same_exam_condition_key(exam), test_order_value(exam)), True),
            "group_asc": (lambda exam: (normalize_group(exam.get("group", "")), reverse_latest_year_sort_value(exam), same_exam_condition_key(exam), test_order_value(exam)), False),
            "group_desc": (lambda exam: (normalize_group(exam.get("group", "")), reverse_latest_year_sort_value(exam), same_exam_condition_key(exam), test_order_value(exam)), True),
            "test_type_asc": (lambda exam: (display_test_type(exam), reverse_latest_year_sort_value(exam), same_exam_condition_key(exam), test_order_value(exam)), False),
            "test_type_desc": (lambda exam: (display_test_type(exam), reverse_latest_year_sort_value(exam), same_exam_condition_key(exam), test_order_value(exam)), True),
            "source_site_asc": (lambda exam: (exam.get("sourceSite", ""), reverse_latest_year_sort_value(exam), same_exam_condition_key(exam), test_order_value(exam)), False),
            "source_site_desc": (lambda exam: (exam.get("sourceSite", ""), reverse_latest_year_sort_value(exam), same_exam_condition_key(exam), test_order_value(exam)), True),
        }
        key, reverse = sorters.get(sort_key, sorters["year_desc"])
        self.filtered.sort(key=key, reverse=reverse)

    def render_table(self):
        self.update_heading_sort_indicators()
        self.tree.delete(*self.tree.get_children())
        for exam in self.filtered:
            self.tree.insert(
                "",
                "end",
                iid=exam["id"],
                values=(
                    display_year(exam, self.test_type_display_tick),
                    exam.get("subject", ""),
                    exam.get("teacher", ""),
                    normalize_group(exam.get("group", "")),
                    display_test_type(exam, self.test_type_display_tick),
                    exam.get("sourceSite", ""),
                ),
            )
        self.count_label.config(text=f"{len(self.filtered)}件")
        self.update_bulk_download_button()
        self.update_selected_detail()

    def bulk_download_candidates(self):
        return [
            exam
            for exam in self.filtered
            if exam.get("driveUrl") and not local_file_exists(exam) and not self.is_manual_exam(exam)
        ]

    def update_bulk_download_button(self):
        state = "normal" if self.bulk_download_candidates() and not self.download_active else "disabled"
        self.bulk_download_button.configure(state=state)

    def schedule_test_type_display_refresh(self):
        self.after(2000, self.refresh_alternating_test_type_display)

    def refresh_alternating_test_type_display(self):
        self.test_type_display_tick += 1
        for item_id in self.tree.get_children():
            exam = next((item for item in self.exams if item.get("id") == item_id), None)
            if not exam or (len(exam_test_types(exam)) < 2 and len(exam_years(exam)) < 2):
                continue
            values = list(self.tree.item(item_id, "values"))
            if len(values) >= 5:
                values[0] = display_year(exam, self.test_type_display_tick)
                values[4] = display_test_type(exam, self.test_type_display_tick)
                self.tree.item(item_id, values=values)
        self.schedule_test_type_display_refresh()

    def is_filter_focus(self, widget):
        return widget in (
            self.landing_subject_entry,
            self.landing_teacher_entry,
            self.landing_year_combo,
            self.landing_group_combo,
            self.landing_test_type_combo,
            self.landing_source_site_combo,
            self.subject_entry,
            self.teacher_entry,
            self.year_combo,
            self.group_combo,
            self.test_type_combo,
            self.source_site_combo,
        )

    def focus_widget(self, widget):
        self.after_idle(lambda: widget.focus_set() if widget.winfo_exists() else None)

    def focus_landing_search(self):
        self.focus_widget(self.landing_subject_entry)

    def focus_results_table(self, select_first=False):
        def apply_focus():
            if not self.tree.winfo_exists():
                return
            children = self.tree.get_children()
            if select_first and children and not self.tree.selection():
                self.tree.selection_set(children[0])
                self.tree.focus(children[0])
                self.tree.see(children[0])
                self.update_selected_detail()
            self.tree.focus_set()

        self.after_idle(apply_focus)

    def close_dialog(self, window):
        if window and window.winfo_exists():
            window.destroy()
        self.after_idle(self.restore_main_focus)

    def restore_main_focus(self):
        if not self.winfo_exists():
            return
        self.lift()
        self.focus_force()
        if self.landing_frame.winfo_ismapped():
            self.focus_landing_search()
        elif self.tree.get_children():
            self.focus_results_table(select_first=False)
        else:
            self.focus_set()

    def selected_exam(self):
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("過去問検索", "過去問を選択してください。")
            return None
        exam_id = selection[0]
        return next((exam for exam in self.exams if exam.get("id") == exam_id), None)

    def group_filtered_exams(self, exams):
        grouped = {}
        result = []
        matching_ids = {exam.get("id") for exam in exams}
        for exam in exams:
            page_group = exam.get("pageGroup")
            if not page_group:
                result.append(exam)
                continue
            if page_group in grouped:
                continue
            pages = self.page_group_exams(exam)
            representative = next(
                (page for page in pages if page.get("id") in matching_ids),
                exam,
            )
            grouped[page_group] = representative
            result.append(representative)
        return result

    def page_group_exams(self, exam):
        page_group = exam.get("pageGroup")
        if not page_group:
            return [exam]
        pages = [
            item
            for item in self.exams
            if item.get("pageGroup") == page_group and item.get("driveUrl")
        ]
        pages.sort(key=lambda item: (int(item.get("pageNumber") or 0), item.get("id", "")))
        return pages or [exam]

    def update_selected_detail(self):
        selection = self.tree.selection()
        if not selection:
            self.local_file_var.set("ローカルファイル: 未選択")
            self.source_site_var.set("取得元: 未選択")
            self.notes_var.set("注釈: 未選択")
            self.feedback_summary_var.set("メモ: 未選択")
            self.download_button.configure(state="disabled")
            return

        exam = next((item for item in self.exams if item.get("id") == selection[0]), None)
        if not exam:
            return

        local_file = exam.get("localFile") if local_file_exists(exam) else "なし"
        source_site = exam.get("sourceSite") or "なし"
        notes = exam.get("notes") or "なし"
        self.local_file_var.set(f"ローカルファイル: {local_file}")
        self.source_site_var.set(f"取得元: {source_site}")
        self.notes_var.set(f"注釈: {notes}")
        self.feedback_summary_var.set(self.feedback_summary_for_exam(exam))
        download_state = "disabled" if local_file_exists(exam) or self.download_active or self.is_manual_exam(exam) else "normal"
        self.download_button.configure(state=download_state)

    def read_feedback(self):
        if not FEEDBACK_PATH.exists():
            return []
        try:
            return json.loads(FEEDBACK_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            messagebox.showwarning("過去問検索", "feedback.jsonを読み込めませんでした。")
            return []

    def write_feedback(self):
        FEEDBACK_PATH.parent.mkdir(exist_ok=True)
        FEEDBACK_PATH.write_text(json.dumps(self.feedback, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def read_edit_history(self):
        if not EDIT_HISTORY_PATH.exists():
            return []
        try:
            return json.loads(EDIT_HISTORY_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []

    def write_edit_history(self, history):
        EDIT_HISTORY_PATH.parent.mkdir(exist_ok=True)
        EDIT_HISTORY_PATH.write_text(json.dumps(history[-EDIT_HISTORY_LIMIT:], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def exam_edit_snapshot(self, exam):
        keys = (
            "id",
            "year",
            "teacher",
            "subject",
            "group",
            "testType",
            "testNumber",
            "sourceSite",
            "localFile",
            "driveUrl",
            "notes",
            "alternateTestTypes",
            "alternateYears",
            "pageGroup",
            "pageNumber",
        )
        return {key: exam.get(key) for key in keys if key in exam}

    def record_edit_history(self, before, after):
        changed_fields = sorted(key for key in set(before) | set(after) if before.get(key) != after.get(key))
        if not changed_fields:
            return
        history = self.read_edit_history()
        history.append({
            "editedAt": datetime.now().isoformat(timespec="seconds"),
            "examId": after.get("id") or before.get("id"),
            "changedFields": changed_fields,
            "before": before,
            "after": after,
        })
        self.write_edit_history(history)

    def feedback_for_exam(self, exam_id):
        return [item for item in self.feedback if item.get("examId") == exam_id and item.get("status", "open") == "open"]

    def feedback_summary(self, exam_id):
        items = self.feedback_for_exam(exam_id)
        if not items:
            return "メモ: なし"
        latest = items[-1]
        comment = latest.get("comment", "").replace("\n", " ")
        return f"メモ: {len(items)}件 / 最新: {comment}"

    def feedback_summary_for_exam(self, exam):
        items = []
        for page in self.page_group_exams(exam):
            items.extend(self.feedback_for_exam(page["id"]))
        if not items:
            return "メモ: なし"
        latest = items[-1]
        comment = latest.get("comment", "").replace("\n", " ")
        return f"メモ: {len(items)}件 / 最新: {comment}"

    def save_feedback(self):
        exam = self.selected_exam()
        if not exam:
            return
        comment = self.feedback_text.get("1.0", "end").strip()
        if not comment:
            messagebox.showinfo("過去問検索", "保存するメモを入力してください。")
            return

        self.add_feedback(exam, comment)
        self.feedback_text.delete("1.0", "end")
        self.render_table()
        self.status_var.set("メモを保存しました")

    def open_add_exam_dialog(self):
        window = tk.Toplevel(self)
        window.title("過去問を追加")
        window.geometry("560x720")
        window.minsize(520, 660)
        window.columnconfigure(0, weight=1)
        window.transient(self)
        window.lift()
        window.protocol("WM_DELETE_WINDOW", lambda: self.close_dialog(window))

        form = ttk.Frame(window, padding=16)
        form.grid(row=0, column=0, sticky="nsew")
        form.columnconfigure(1, weight=1)

        values = {
            "file": tk.StringVar(),
            "year": tk.StringVar(value="20"),
            "term": tk.StringVar(value="前期"),
            "teacher": tk.StringVar(),
            "subject": tk.StringVar(),
            "group": tk.StringVar(),
            "testType": tk.StringVar(value="定期テスト"),
            "testNumber": tk.StringVar(),
        }

        ttk.Label(form, text="過去問を追加", font=("", 20, "bold")).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 14))
        file_entry = self.add_form_row(form, "ファイル", values["file"], 1, browse_command=lambda: self.choose_exam_file(values["file"]))
        year_entry = self.add_year_row(form, values["year"], 2)
        term_combo = self.add_form_combo(form, "前期/後期", values["term"], 3, TERMS)
        teacher_entry = self.add_form_row(form, "教師名", values["teacher"], 4)
        subject_entry = self.add_form_row(form, "科目名", values["subject"], 5)
        group_combo = self.add_form_combo(form, "科目群", values["group"], 6, COURSE_GROUPS)
        test_type_combo = self.add_form_combo(form, "テスト種別", values["testType"], 7, TEST_TYPES)
        test_number_label = ttk.Label(form, text="小テスト番号")
        test_number_entry = ttk.Entry(form, textvariable=values["testNumber"])
        self.guard_input_source_switch_space(test_number_entry)

        ttk.Label(form, text="注釈").grid(row=9, column=0, sticky="nw", padx=(0, 10), pady=(8, 4))
        notes = tk.Text(form, height=5, wrap="word", relief="solid", borderwidth=1, padx=8, pady=8)
        self.guard_input_source_switch_space(notes)
        notes.grid(row=9, column=1, columnspan=2, sticky="ew", pady=(8, 4))

        button_frame = ttk.Frame(form)
        button_frame.grid(row=10, column=0, columnspan=3, sticky="ew", pady=(18, 0))
        button_frame.columnconfigure(0, weight=1)
        button_frame.columnconfigure(1, weight=1)
        ttk.Button(
            button_frame,
            text="追加",
            command=lambda: self.add_exam(values, notes, window),
        ).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(button_frame, text="キャンセル", command=lambda: self.close_dialog(window)).grid(row=0, column=1, sticky="ew", padx=(6, 0))
        self.update_test_number_visibility(values["testType"], values["testNumber"], test_number_label, test_number_entry)
        values["testType"].trace_add(
            "write",
            lambda *_: self.update_test_number_visibility(values["testType"], values["testNumber"], test_number_label, test_number_entry),
        )
        self.bind_return_focus(file_entry, year_entry)
        self.bind_return_focus(year_entry, term_combo)
        self.bind_return_focus(term_combo, teacher_entry)
        self.bind_return_focus(teacher_entry, subject_entry)
        self.bind_return_focus(subject_entry, group_combo)
        self.bind_return_focus(group_combo, test_type_combo)
        test_type_combo.bind(
            "<Return>",
            lambda _: self.focus_test_number_or_notes(values["testType"], test_number_entry, notes),
        )
        self.bind_return_focus(test_number_entry, notes)
        self.bind_teacher_cleaner(values["teacher"])
        self.enable_undo_for_form(file_entry, year_entry, teacher_entry, subject_entry, test_number_entry, notes)
        window.after_idle(lambda: (window.focus_force(), year_entry.focus_set()) if window.winfo_exists() else None)

    def enable_undo_for_form(self, *widgets):
        for widget in widgets:
            self.guard_input_source_switch_space(widget)
            if isinstance(widget, tk.Text):
                widget.configure(undo=True, maxundo=100, autoseparators=True)
                widget.bind("<Control-z>", self.undo_text_widget, add="+")
                widget.bind("<Command-z>", self.undo_text_widget, add="+")
            elif isinstance(widget, ttk.Entry):
                self.enable_entry_undo(widget)

    def undo_text_widget(self, event):
        try:
            event.widget.edit_undo()
        except tk.TclError:
            pass
        return "break"

    def enable_entry_undo(self, entry):
        state = {
            "history": [entry.get()],
            "undoing": False,
        }

        def remember():
            if not entry.winfo_exists() or state["undoing"]:
                return
            value = entry.get()
            if state["history"][-1] != value:
                state["history"].append(value)
                if len(state["history"]) > 100:
                    state["history"].pop(0)

        def schedule_remember(_event=None):
            entry.after_idle(remember)

        def undo(_event=None):
            if len(state["history"]) <= 1:
                return "break"
            state["undoing"] = True
            state["history"].pop()
            previous = state["history"][-1]
            entry.delete(0, "end")
            entry.insert(0, previous)
            entry.icursor("end")
            state["undoing"] = False
            return "break"

        entry.bind("<KeyRelease>", schedule_remember, add="+")
        entry.bind("<<Paste>>", schedule_remember, add="+")
        entry.bind("<<Cut>>", schedule_remember, add="+")
        entry.bind("<Control-z>", undo, add="+")
        entry.bind("<Command-z>", undo, add="+")

    def bind_teacher_cleaner(self, variable):
        cleaning = {"active": False}

        def clean(*_):
            if cleaning["active"]:
                return
            value = variable.get()
            cleaned = clean_teacher_name(value)
            if value == cleaned:
                return
            cleaning["active"] = True
            variable.set(cleaned)
            cleaning["active"] = False

        variable.trace_add("write", clean)

    def bind_return_focus(self, widget, next_widget):
        widget.bind("<Return>", lambda _: self.focus_next_widget(next_widget))

    def focus_next_widget(self, widget):
        widget.focus_set()
        return "break"

    def focus_test_number_or_notes(self, test_type_var, test_number_entry, notes_widget):
        if test_type_var.get() == "小テスト":
            test_number_entry.focus_set()
        else:
            notes_widget.focus_set()
        return "break"

    def update_test_number_visibility(self, test_type_var, test_number_var, label, entry, row=8):
        if test_type_var.get() == "小テスト":
            label.grid(row=row, column=0, sticky="w", padx=(0, 10), pady=5)
            entry.grid(row=row, column=1, columnspan=2, sticky="ew", pady=5)
        else:
            test_number_var.set("")
            label.grid_remove()
            entry.grid_remove()

    def add_year_row(self, parent, variable, row):
        ttk.Label(parent, text="年度").grid(row=row, column=0, sticky="w", padx=(0, 10), pady=5)
        validate_command = (self.register(self.validate_year_edit), "%P")
        entry = ttk.Entry(parent, textvariable=variable, validate="key", validatecommand=validate_command)
        self.guard_input_source_switch_space(entry)
        entry.grid(row=row, column=1, columnspan=2, sticky="ew", pady=5)
        entry.bind("<BackSpace>", self.protect_year_prefix)
        entry.bind("<Delete>", self.protect_year_prefix)
        entry.bind("<Home>", self.move_year_cursor_to_editable_part)
        entry.bind("<Left>", self.keep_year_cursor_after_prefix_event, add="+")
        entry.bind("<ButtonRelease-1>", self.keep_year_cursor_after_prefix_event, add="+")
        entry.bind("<KeyRelease>", self.keep_year_cursor_after_prefix_event, add="+")
        self.keep_year_cursor_after_prefix(entry)
        return entry

    def validate_year_edit(self, proposed):
        return bool(re.fullmatch(r"20\d{0,2}", proposed))

    def protect_year_prefix(self, event):
        entry = event.widget
        try:
            selection_start = entry.index("sel.first")
            selection_end = entry.index("sel.last")
            if selection_start < 2:
                if selection_end <= 2:
                    entry.icursor(2)
                    return "break"
                entry.selection_range(2, selection_end)
        except tk.TclError:
            if entry.index("insert") <= 2:
                entry.icursor(2)
                return "break"
        return None

    def move_year_cursor_to_editable_part(self, event):
        event.widget.icursor(2)
        return "break"

    def keep_year_cursor_after_prefix_event(self, event):
        self.after_idle(lambda: self.keep_year_cursor_after_prefix(event.widget))

    def keep_year_cursor_after_prefix(self, entry):
        if not entry.winfo_exists():
            return
        if entry.index("insert") < 2:
            entry.icursor(2)

    def add_form_row(self, parent, label, variable, row, browse_command=None):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=5)
        entry = ttk.Entry(parent, textvariable=variable)
        self.guard_input_source_switch_space(entry)
        if browse_command:
            entry.grid(row=row, column=1, sticky="ew", pady=5)
            ttk.Button(parent, text="選択", command=browse_command).grid(row=row, column=2, sticky="ew", padx=(8, 0), pady=5)
        else:
            entry.grid(row=row, column=1, columnspan=2, sticky="ew", pady=5)
        return entry

    def add_form_combo(self, parent, label, variable, row, values):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=5)
        combo = ttk.Combobox(parent, textvariable=variable, values=values, state="readonly")
        combo.grid(row=row, column=1, columnspan=2, sticky="ew", pady=5)
        return combo

    def choose_exam_file(self, file_var):
        filename = filedialog.askopenfilename(title="追加する過去問ファイルを選択")
        if filename:
            file_var.set(filename)

    def add_exam(self, values, notes_widget, window):
        year = values["year"].get().strip()
        term = values["term"].get().strip()
        full_year = f"{year}{term}" if year and term else ""
        subject = normalize_hyphens(values["subject"].get()).strip()
        teacher = clean_teacher_name(values["teacher"].get())
        group = values["group"].get().strip()
        test_type = values["testType"].get().strip()
        test_number = values["testNumber"].get().strip()
        file_path = values["file"].get().strip()

        if not file_path or not year or not term or not teacher or not subject or not group or not test_type:
            messagebox.showinfo("過去問検索", "ファイル、年度、前期/後期、教師名、科目名、科目群、テスト種別は必須です。")
            return
        if not re.fullmatch(r"20\d{2}", year):
            messagebox.showinfo("過去問検索", "年度は20から始まる半角数字4桁で入力してください。")
            return
        if test_number and not re.fullmatch(r"[1-9]\d*", test_number):
            messagebox.showinfo("過去問検索", "小テスト番号は半角数字で入力してください。")
            return

        local_file = ""
        source = Path(file_path)
        if not source.exists():
            messagebox.showwarning("過去問検索", f"ファイルが見つかりません。\n{source}")
            return
        MANUAL_FILES_DIR.mkdir(parents=True, exist_ok=True)
        target = MANUAL_FILES_DIR / exam_rule_filename(subject, teacher, full_year, source.suffix, test_type, test_number)
        if target.exists():
            messagebox.showwarning("過去問検索", f"同名ファイルがすでに存在します。\n{target.name}")
            return
        shutil.copyfile(source, target)
        local_file = f"./files/manual/{target.name}"

        now = datetime.now().strftime("%Y%m%d%H%M%S")
        exam = {
            "id": f"manual-{now}-{safe_filename_part(subject)}",
            "year": full_year,
            "teacher": teacher,
            "subject": subject,
            "group": group,
            "testType": test_type,
            "sourceSite": "手動追加",
            "localFile": local_file,
            "driveUrl": "",
            "notes": normalize_hyphens(notes_widget.get("1.0", "end")).strip(),
        }
        if test_type == "小テスト" and test_number:
            exam["testNumber"] = test_number
        self.exams.append(exam)
        self.mirror_manual_file(local_file)
        write_exams(self.exams)
        self.refresh_filter_options()
        if self.has_searched:
            self.apply_filters()
        self.status_var.set("過去問を追加しました")
        messagebox.showinfo("過去問検索", "過去問を追加しました。")
        self.close_dialog(window)

    def open_edit_exam_dialog(self, exam=None):
        exam = exam or self.selected_exam()
        if not exam:
            return

        window = tk.Toplevel(self)
        window.title("過去問を編集")
        window.geometry("560x640")
        window.minsize(520, 580)
        window.columnconfigure(0, weight=1)
        window.transient(self)
        window.lift()
        window.protocol("WM_DELETE_WINDOW", lambda: self.close_dialog(window))

        form = ttk.Frame(window, padding=16)
        form.grid(row=0, column=0, sticky="nsew")
        form.columnconfigure(1, weight=1)

        year, term = split_year_term(exam.get("year", ""))
        values = {
            "year": tk.StringVar(value=year or "20"),
            "term": tk.StringVar(value=term),
            "teacher": tk.StringVar(value=exam.get("teacher", "")),
            "subject": tk.StringVar(value=exam.get("subject", "")),
            "group": tk.StringVar(value=exam.get("group", "")),
            "testType": tk.StringVar(value=exam.get("testType", "定期テスト")),
            "testNumber": tk.StringVar(value=str(exam.get("testNumber") or "")),
        }

        ttk.Label(form, text="過去問を編集", font=("", 20, "bold")).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 14))
        year_entry = self.add_year_row(form, values["year"], 1)
        term_combo = self.add_form_combo(form, "前期/後期", values["term"], 2, ("", *TERMS))
        teacher_entry = self.add_form_row(form, "教師名", values["teacher"], 3)
        subject_entry = self.add_form_row(form, "科目名", values["subject"], 4)
        group_combo = self.add_form_combo(form, "科目群", values["group"], 5, COURSE_GROUPS)
        test_type_combo = self.add_form_combo(form, "テスト種別", values["testType"], 6, TEST_TYPES)
        test_number_label = ttk.Label(form, text="小テスト番号")
        test_number_entry = ttk.Entry(form, textvariable=values["testNumber"])
        self.guard_input_source_switch_space(test_number_entry)

        ttk.Label(form, text="注釈").grid(row=8, column=0, sticky="nw", padx=(0, 10), pady=(8, 4))
        notes = tk.Text(form, height=5, wrap="word", relief="solid", borderwidth=1, padx=8, pady=8)
        self.guard_input_source_switch_space(notes)
        notes.grid(row=8, column=1, columnspan=2, sticky="ew", pady=(8, 4))
        notes.insert("1.0", exam.get("notes", ""))

        button_frame = ttk.Frame(form)
        button_frame.grid(row=9, column=0, columnspan=3, sticky="ew", pady=(18, 0))
        button_frame.columnconfigure(0, weight=1)
        button_frame.columnconfigure(1, weight=1)
        button_frame.columnconfigure(2, weight=1)
        ttk.Button(button_frame, text="保存", command=lambda: self.save_exam_edits(exam, values, notes, window)).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        if self.is_manual_exam(exam):
            ttk.Button(button_frame, text="削除", command=lambda: self.delete_manual_exam(exam, window)).grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(button_frame, text="キャンセル", command=lambda: self.close_dialog(window)).grid(row=0, column=2, sticky="ew", padx=(6, 0))

        self.update_test_number_visibility(values["testType"], values["testNumber"], test_number_label, test_number_entry, row=7)
        values["testType"].trace_add(
            "write",
            lambda *_: self.update_test_number_visibility(values["testType"], values["testNumber"], test_number_label, test_number_entry, row=7),
        )
        self.bind_return_focus(year_entry, term_combo)
        self.bind_return_focus(term_combo, teacher_entry)
        self.bind_return_focus(teacher_entry, subject_entry)
        self.bind_return_focus(subject_entry, group_combo)
        self.bind_return_focus(group_combo, test_type_combo)
        test_type_combo.bind("<Return>", lambda _: self.focus_test_number_or_notes(values["testType"], test_number_entry, notes))
        self.bind_return_focus(test_number_entry, notes)
        self.bind_teacher_cleaner(values["teacher"])
        self.enable_undo_for_form(year_entry, teacher_entry, subject_entry, test_number_entry, notes)
        window.after_idle(lambda: (window.focus_force(), year_entry.focus_set()) if window.winfo_exists() else None)

    def save_exam_edits(self, exam, values, notes_widget, window):
        year = values["year"].get().strip()
        term = values["term"].get().strip()
        teacher = clean_teacher_name(values["teacher"].get())
        subject = normalize_hyphens(values["subject"].get()).strip()
        group = values["group"].get().strip()
        test_type = values["testType"].get().strip()
        test_number = values["testNumber"].get().strip()

        if not year or not subject or not group or not test_type:
            messagebox.showinfo("過去問検索", "年度、科目名、科目群、テスト種別は必須です。")
            return
        if not re.fullmatch(r"20\d{2}", year):
            messagebox.showinfo("過去問検索", "年度は20から始まる半角数字4桁で入力してください。")
            return
        if test_number and not re.fullmatch(r"[1-9]\d*", test_number):
            messagebox.showinfo("過去問検索", "小テスト番号は半角数字で入力してください。")
            return

        target = next((item for item in self.exams if item.get("id") == exam.get("id")), None)
        if not target:
            messagebox.showwarning("過去問検索", "編集対象が見つかりません。")
            return
        before_snapshot = self.exam_edit_snapshot(target)
        old_local_file = target.get("localFile")
        new_local_file = self.renamed_local_file_for_edit(
            target,
            subject,
            teacher,
            f"{year}{term}",
            test_type,
            test_number,
        )
        if new_local_file is None:
            return
        metadata_updates = {
            "year": f"{year}{term}",
            "teacher": teacher,
            "subject": subject,
            "group": group,
            "testType": test_type,
        }
        for metadata_target in self.edit_metadata_targets(target):
            metadata_target.update(metadata_updates)
            if test_type == "小テスト" and test_number:
                metadata_target["testNumber"] = test_number
            else:
                metadata_target.pop("testNumber", None)
        target["notes"] = normalize_hyphens(notes_widget.get("1.0", "end")).strip()
        if new_local_file:
            self.update_shared_local_file_references(old_local_file, new_local_file)

        self.record_edit_history(before_snapshot, self.exam_edit_snapshot(target))
        self.mirror_manual_file(target.get("localFile"))
        write_exams(self.exams)
        self.refresh_filter_options()
        if self.has_searched:
            self.apply_filters()
        self.status_var.set("過去問を編集しました")
        messagebox.showinfo("過去問検索", "過去問を編集しました。")
        self.close_dialog(window)

    def edit_metadata_targets(self, exam):
        page_group = exam.get("pageGroup")
        if not page_group:
            return [exam]
        targets = [item for item in self.exams if item.get("pageGroup") == page_group]
        return targets or [exam]

    def update_shared_local_file_references(self, old_local_file, new_local_file):
        if not old_local_file or not new_local_file:
            return
        for item in self.exams:
            if item.get("localFile") == old_local_file:
                item["localFile"] = new_local_file

    def renamed_local_file_for_edit(self, exam, subject, teacher, year, test_type, test_number):
        current_path = local_file_path(exam)
        if not current_path or not current_path.exists():
            return ""
        try:
            current_path.resolve().relative_to(ROOT.resolve())
        except ValueError:
            return ""
        suffix = current_path.suffix or ".pdf"
        if self.is_manual_exam(exam):
            target_name = exam_rule_filename(subject, teacher, year, suffix, test_type, test_number)
        else:
            target_name = downloaded_rule_filename(
                subject,
                teacher,
                year,
                suffix,
                test_type,
                test_number,
                exam.get("sourceSite", ""),
            )
        target_dir = MANUAL_FILES_DIR if self.is_manual_exam(exam) else DRIVE_FILES_DIR
        target_path = target_dir / target_name
        if current_path.resolve() == target_path.resolve():
            return ""
        if target_path.exists():
            messagebox.showwarning("過去問検索", f"同名ファイルがすでに存在します。\n{target_path.name}")
            return None
        target_dir.mkdir(parents=True, exist_ok=True)
        old_local_file = exam.get("localFile")
        current_path.rename(target_path)
        self.remove_mirrored_manual_file(old_local_file)
        return f"./files/{target_dir.name}/{target_path.name}"

    def is_manual_exam(self, exam):
        return exam.get("sourceSite") == "手動追加" or str(exam.get("id", "")).startswith("manual-")

    def delete_manual_exam(self, exam, window):
        if not self.is_manual_exam(exam):
            messagebox.showinfo("過去問検索", "削除できるのは手動追加の過去問だけです。")
            return
        first = messagebox.askyesno("削除確認", "この手動追加の過去問を削除しますか？")
        if not first:
            return
        second = messagebox.askyesno("最終確認", "本当に削除しますか？この操作は取り消せません。")
        if not second:
            return
        self.exams = [item for item in self.exams if item.get("id") != exam.get("id")]
        local_path = local_file_path(exam)
        if local_path and local_path.exists():
            try:
                local_path.resolve().relative_to(ROOT.resolve())
            except ValueError:
                pass
            else:
                local_path.unlink()
        self.remove_mirrored_manual_file(exam.get("localFile"))
        write_exams(self.exams)
        self.refresh_filter_options()
        if self.has_searched:
            self.apply_filters()
        self.status_var.set("過去問を削除しました")
        messagebox.showinfo("過去問検索", "過去問を削除しました。")
        self.close_dialog(window)

    def open_detail_page(self, exam=None):
        exam = exam or self.selected_exam()
        if not exam:
            return

        window = tk.Toplevel(self)
        window.title(f"{exam.get('subject', '過去問')} - 詳細")
        window.geometry("780x660")
        window.minsize(640, 540)
        window.columnconfigure(0, weight=1)
        window.rowconfigure(1, weight=1)
        window.transient(self)
        window.lift()
        window.protocol("WM_DELETE_WINDOW", lambda: self.close_dialog(window))

        header = ttk.Frame(window, padding=16)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text=exam.get("subject") or "科目名未設定", font=("", 22, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(header, text=f"{exam.get('year', '')} / {exam.get('teacher') or '教師名未設定'}").grid(row=1, column=0, sticky="w", pady=(4, 0))

        body = ttk.Frame(window, padding=(16, 0, 16, 16))
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(1, weight=1)

        info = ttk.LabelFrame(body, text="過去問情報", padding=12)
        info.grid(row=0, column=0, sticky="ew")
        info.columnconfigure(1, weight=1)
        rows = [
            ("年度", exam.get("year", "")),
            ("教師名", exam.get("teacher", "") or "未設定"),
            ("科目名", exam.get("subject", "") or "未設定"),
            ("科目群", exam.get("group", "") or "未設定"),
            ("テスト種別", display_test_type(exam) or "未設定"),
            ("取得元", exam.get("sourceSite", "") or "未設定"),
            ("ファイル状態", "ローカル保存済み" if local_file_exists(exam) else "Drive参照" if exam.get("driveUrl") else "未登録"),
            ("ローカルファイル", exam.get("localFile") if local_file_exists(exam) else "なし"),
            ("注釈", exam.get("notes", "") or "なし"),
        ]
        if exam.get("testType") == "小テスト" and exam.get("testNumber"):
            rows.insert(5, ("小テスト番号", exam.get("testNumber")))
        for row, (label, value) in enumerate(rows):
            ttk.Label(info, text=label).grid(row=row, column=0, sticky="nw", padx=(0, 12), pady=3)
            self.add_selectable_info_value(info, value, row)

        feedback_box = ttk.LabelFrame(body, text="メモ", padding=12)
        feedback_box.grid(row=1, column=0, sticky="nsew", pady=(12, 0))
        feedback_box.columnconfigure(0, weight=1)
        feedback_box.rowconfigure(0, weight=1)

        existing = tk.Text(
            feedback_box,
            height=7,
            wrap="word",
            state="normal",
            relief="solid",
            borderwidth=1,
            padx=8,
            pady=8,
        )
        existing.grid(row=0, column=0, columnspan=2, sticky="nsew")
        self.guard_input_source_switch_space(existing)
        existing.insert("1.0", self.detail_feedback_text_for_exam(exam))
        existing.configure(state="disabled")

        ttk.Label(feedback_box, text="新しいメモ").grid(row=1, column=0, sticky="w", pady=(10, 4))
        new_feedback = tk.Text(feedback_box, height=4, wrap="word", relief="solid", borderwidth=1, padx=8, pady=8)
        self.guard_input_source_switch_space(new_feedback)
        new_feedback.grid(row=2, column=0, sticky="ew")
        ttk.Button(
            feedback_box,
            text="メモを保存",
            command=lambda: self.save_detail_feedback(exam, new_feedback, existing),
        ).grid(row=2, column=1, sticky="ns", padx=(10, 0))

        actions = ttk.Frame(window, padding=(16, 0, 16, 16))
        actions.grid(row=2, column=0, sticky="ew")
        actions.columnconfigure(5, weight=1)
        ttk.Button(actions, text="開く", command=lambda: self.open_exam_preferred(exam)).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(actions, text="編集", command=lambda: self.open_edit_exam_dialog(exam)).grid(row=0, column=1, padx=(0, 8))
        ttk.Button(actions, text="ファイルの場所を開く", command=lambda: self.open_exam_file_location(exam)).grid(row=0, column=2, padx=(0, 8))
        download_state = "disabled" if local_file_exists(exam) or self.is_manual_exam(exam) else "normal"
        ttk.Button(
            actions,
            text="Driveからローカル保存",
            command=lambda: self.download_exam_from_detail(exam, window),
            state=download_state,
        ).grid(row=0, column=3, padx=(0, 8))
        ttk.Button(actions, text="閉じる", command=lambda: self.close_dialog(window)).grid(row=0, column=4, padx=(0, 8))
        window.after_idle(lambda: (window.focus_force(), new_feedback.focus_set()) if window.winfo_exists() else None)

    def add_selectable_info_value(self, parent, value, row):
        text = str(value)
        line_count = sum(max(1, (len(line) + 54) // 55) for line in text.splitlines() or [""])
        widget = tk.Text(
            parent,
            height=line_count,
            width=1,
            wrap="word",
            font="TkDefaultFont",
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            padx=0,
            pady=0,
            cursor="xterm",
            background=self.cget("background"),
        )
        widget.insert("1.0", text)
        widget.configure(state="disabled")
        widget.grid(row=row, column=1, sticky="ew", pady=3)
        return widget

    def detail_feedback_text(self, exam_id):
        items = self.feedback_for_exam(exam_id)
        if not items:
            return "メモはまだありません。"
        return "\n".join(self.feedback_history_line(item) for item in items)

    def feedback_history_line(self, item, prefix=""):
        created_at = str(item.get("createdAt", "")).replace("T", " ")
        comment = " / ".join(
            line.strip()
            for line in str(item.get("comment", "")).splitlines()
            if line.strip()
        )
        return f"{prefix}{created_at}  {comment}".rstrip()

    def detail_feedback_text_for_exam(self, exam):
        lines = []
        for page in self.page_group_exams(exam):
            page_label = f"{page.get('pageNumber')}ファイル目" if exam.get("pageGroup") else ""
            for item in self.feedback_for_exam(page["id"]):
                prefix = f"{page_label} " if page_label else ""
                lines.append(self.feedback_history_line(item, prefix))
        return "\n".join(lines) if lines else "メモはまだありません。"

    def save_detail_feedback(self, exam, text_widget, existing_widget):
        comment = text_widget.get("1.0", "end").strip()
        if not comment:
            messagebox.showinfo("過去問検索", "保存するメモを入力してください。")
            return
        self.add_feedback(exam, comment)
        text_widget.delete("1.0", "end")
        existing_widget.configure(state="normal")
        existing_widget.delete("1.0", "end")
        existing_widget.insert("1.0", self.detail_feedback_text_for_exam(exam))
        existing_widget.configure(state="disabled")
        self.render_table()
        self.update_selected_detail()
        self.status_var.set("メモを保存しました")
        messagebox.showinfo("過去問検索", "メモを保存しました。")

    def add_feedback(self, exam, comment):
        now = datetime.now().isoformat(timespec="seconds")
        self.feedback.append({
            "id": f"feedback-{now}-{exam['id']}",
            "examId": exam["id"],
            "createdAt": now,
            "status": "open",
            "comment": comment,
            "snapshot": {
                "year": exam.get("year", ""),
                "subject": exam.get("subject", ""),
                "teacher": exam.get("teacher", ""),
                "group": exam.get("group", ""),
                "testType": exam.get("testType", ""),
                "testNumber": exam.get("testNumber", ""),
                "sourceSite": exam.get("sourceSite", ""),
            },
        })
        self.write_feedback()

    def open_exam_preferred(self, exam):
        if local_file_exists(exam):
            self.open_path(exam["localFile"])
        else:
            self.open_exam_drive_url(exam)

    def open_exam_drive_url(self, exam):
        pages = self.page_group_exams(exam)
        if len(pages) > 1:
            page = self.ask_page_to_open(pages)
            if not page:
                return
            webbrowser.open(page["driveUrl"])
        elif pages and pages[0].get("driveUrl"):
            webbrowser.open(pages[0]["driveUrl"])
        else:
            messagebox.showinfo("過去問検索", "ファイルもDriveリンクも登録されていません。")

    def open_exam_file_location(self, exam):
        if local_file_exists(exam):
            self.open_path_location(exam["localFile"])
        else:
            self.open_exam_drive_url(exam)

    def ask_page_to_open(self, pages):
        window = tk.Toplevel(self)
        window.title("ファイルを選択")
        window.geometry("420x150")
        window.resizable(False, False)
        window.transient(self)
        window.grab_set()
        window.columnconfigure(0, weight=1)

        ttk.Label(window, text="Google Driveで開くファイル").grid(row=0, column=0, sticky="w", padx=16, pady=(16, 6))
        choices = []
        page_by_label = {}
        for index, page in enumerate(pages, start=1):
            page_number = page.get("pageNumber") or index
            label = f"{page_number}ファイル目"
            filename = self.exam_file_label(page)
            if filename:
                label = f"{label}: {filename}"
            choices.append(label)
            page_by_label[label] = page

        selected = tk.StringVar(value=choices[0] if choices else "")
        combo = ttk.Combobox(window, textvariable=selected, values=choices, state="readonly")
        combo.grid(row=1, column=0, sticky="ew", padx=16)

        result = {"page": None}

        def choose():
            result["page"] = page_by_label.get(selected.get())
            window.destroy()

        buttons = ttk.Frame(window)
        buttons.grid(row=2, column=0, sticky="ew", padx=16, pady=16)
        buttons.columnconfigure(0, weight=1)
        buttons.columnconfigure(1, weight=1)
        ttk.Button(buttons, text="開く", command=choose).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(buttons, text="キャンセル", command=window.destroy).grid(row=0, column=1, sticky="ew", padx=(6, 0))

        combo.focus_set()
        window.wait_window()
        return result["page"]

    def exam_file_label(self, exam):
        notes = exam.get("notes") or ""
        match = re.search(r"ファイル名:\s*([^/]+)", notes)
        if match:
            return match.group(1).strip()
        return Path(exam.get("localFile") or "").name

    def download_exam_from_detail(self, exam, window):
        if self.download_active:
            messagebox.showinfo("過去問検索", "別の保存処理が進行中です。")
            return
        if local_file_exists(exam):
            messagebox.showinfo("過去問検索", "すでにローカルに保存されています。")
            return
        if self.is_manual_exam(exam):
            messagebox.showinfo("過去問検索", "手動追加の過去問はDriveから保存できません。")
            return
        if not exam.get("driveUrl"):
            messagebox.showinfo("過去問検索", "Google Driveリンクが登録されていません。")
            return
        self.status_var.set("Driveから保存中...")
        self.download_active = True
        self.update_bulk_download_button()
        self.download_button.configure(state="disabled")
        thread = threading.Thread(target=self.download_detail_worker, args=(exam["id"], window), daemon=True)
        thread.start()

    def download_detail_worker(self, exam_id, window):
        try:
            result = download_exam_file(exam_id)
            self.after(0, lambda: self.finish_detail_download(result["localFile"], window))
        except Exception as error:
            self.after(0, lambda: self.fail_download(str(error)))

    def finish_detail_download(self, local_file, window):
        self.download_active = False
        self.load_data()
        self.apply_filters()
        self.status_var.set("保存しました")
        messagebox.showinfo("過去問検索", f"ローカルに保存しました。\n{local_file}")
        self.close_dialog(window)

    def open_preferred(self):
        exam = self.selected_exam()
        if not exam:
            return
        self.open_exam_preferred(exam)

    def open_local_file(self):
        exam = self.selected_exam()
        if exam:
            self.open_exam_preferred(exam)

    def open_file_location(self):
        exam = self.selected_exam()
        if exam:
            self.open_exam_file_location(exam)

    def open_path(self, path):
        full_path = local_file_path({"localFile": path}) or Path(path)
        if not full_path.exists():
            messagebox.showwarning("過去問検索", f"ファイルが見つかりません。\n{full_path}")
            return
        if sys.platform == "darwin":
            subprocess.run(["open", str(full_path)], check=False)
        elif sys.platform.startswith("win"):
            subprocess.run(["cmd", "/c", "start", "", str(full_path)], check=False)
        else:
            subprocess.run(["xdg-open", str(full_path)], check=False)

    def open_path_location(self, path):
        full_path = local_file_path({"localFile": path}) or Path(path)
        if not full_path.exists():
            messagebox.showwarning("過去問検索", f"ファイルが見つかりません。\n{full_path}")
            return
        if sys.platform == "darwin":
            subprocess.run(["open", "-R", str(full_path)], check=False)
        elif sys.platform.startswith("win"):
            subprocess.run(["explorer", "/select,", str(full_path)], check=False)
        else:
            subprocess.run(["xdg-open", str(full_path.parent)], check=False)

    def download_selected(self):
        if self.download_active:
            messagebox.showinfo("過去問検索", "別の保存処理が進行中です。")
            return
        exam = self.selected_exam()
        if not exam:
            return
        if local_file_exists(exam):
            messagebox.showinfo("過去問検索", "すでにローカルに保存されています。")
            return
        if self.is_manual_exam(exam):
            messagebox.showinfo("過去問検索", "手動追加の過去問はDriveから保存できません。")
            return
        if not exam.get("driveUrl"):
            messagebox.showinfo("過去問検索", "Google Driveリンクが登録されていません。")
            return

        self.status_var.set("Driveから保存中...")
        self.download_active = True
        self.update_bulk_download_button()
        self.download_button.configure(state="disabled")
        thread = threading.Thread(target=self.download_worker, args=(exam["id"],), daemon=True)
        thread.start()

    def download_worker(self, exam_id):
        try:
            result = download_exam_file(exam_id)
            self.after(0, lambda: self.finish_download(result["localFile"]))
        except Exception as error:
            self.after(0, lambda: self.fail_download(str(error)))

    def finish_download(self, local_file):
        self.download_active = False
        self.load_data()
        self.apply_filters()
        self.status_var.set("保存しました")
        messagebox.showinfo("過去問検索", f"ローカルに保存しました。\n{local_file}")

    def download_filtered(self):
        if self.download_active:
            messagebox.showinfo("過去問検索", "別の保存処理が進行中です。")
            return

        candidates = self.bulk_download_candidates()
        already_downloaded = sum(local_file_exists(exam) for exam in self.filtered)
        manual_items = sum(self.is_manual_exam(exam) and not local_file_exists(exam) for exam in self.filtered)
        without_link = sum(
            not exam.get("driveUrl")
            for exam in self.filtered
            if not local_file_exists(exam) and not self.is_manual_exam(exam)
        )
        if not candidates:
            messagebox.showinfo("過去問検索", "一括ダウンロードできる未保存ファイルはありません。")
            return

        details = [f"検索結果{len(self.filtered)}件のうち、未保存の{len(candidates)}件を保存します。"]
        if already_downloaded:
            details.append(f"保存済み{already_downloaded}件はスキップします。")
        if manual_items:
            details.append(f"手動追加{manual_items}件はスキップします。")
        if without_link:
            details.append(f"Driveリンクなし{without_link}件はスキップします。")
        if not messagebox.askokcancel("検索結果を一括ダウンロード", "\n".join(details)):
            return

        self.download_active = True
        self.download_button.configure(state="disabled")
        self.update_bulk_download_button()
        self.status_var.set(f"一括ダウンロード中... 0/{len(candidates)}件")
        exam_ids = [exam["id"] for exam in candidates]
        thread = threading.Thread(target=self.download_filtered_worker, args=(exam_ids,), daemon=True)
        thread.start()

    def download_filtered_worker(self, exam_ids):
        saved = 0
        skipped = 0
        failures = []
        for index, exam_id in enumerate(exam_ids, start=1):
            try:
                result = download_exam_file(exam_id)
                if result.get("alreadyDownloaded"):
                    skipped += 1
                else:
                    saved += 1
            except Exception as error:
                failures.append((exam_id, str(error)))
            self.after(0, lambda done=index, total=len(exam_ids): self.status_var.set(f"一括ダウンロード中... {done}/{total}件"))
        self.after(0, lambda: self.finish_filtered_download(saved, skipped, failures))

    def finish_filtered_download(self, saved, skipped, failures):
        self.download_active = False
        self.load_data()
        self.apply_filters()
        if failures:
            self.status_var.set("一括ダウンロードが一部失敗しました")
            lines = [f"{saved}件を保存しました。"]
            if skipped:
                lines.append(f"処理中に保存済みとなった{skipped}件をスキップしました。")
            lines.append(f"{len(failures)}件を保存できませんでした。")
            lines.extend(f"{exam_id}: {message}" for exam_id, message in failures[:3])
            messagebox.showwarning("検索結果を一括ダウンロード", "\n".join(lines))
            return
        self.status_var.set("一括ダウンロードしました")
        message = f"{saved}件をローカルに保存しました。"
        if skipped:
            message += f"\n保存済み{skipped}件はスキップしました。"
        messagebox.showinfo("検索結果を一括ダウンロード", message)

    def fail_download(self, message):
        self.download_active = False
        self.update_selected_detail()
        self.update_bulk_download_button()
        self.status_var.set("保存に失敗しました")
        messagebox.showerror("過去問検索", f"Driveから保存できませんでした。\n{message}")


if __name__ == "__main__":
    app = KakomonApp()
    app.mainloop()
