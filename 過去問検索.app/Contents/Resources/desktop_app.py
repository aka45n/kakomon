from pathlib import Path
from datetime import datetime
import shutil
import json
import os
import re
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import webbrowser

from drive_downloader import DATA_PATH, FILES_DIR, ROOT, download_exam_file


FEEDBACK_PATH = ROOT / "data" / "feedback.json"
SEED_ROOT = Path(os.environ["KAKOMON_SEED_ROOT"]) if os.environ.get("KAKOMON_SEED_ROOT") else None
TEST_TYPES = ("小テスト", "定期テスト")
COURSE_GROUPS = (
    "人社群",
    "自然群",
    "外国語群",
    "情報群",
    "健康群",
    "キャリア形成科目群",
    "統合科学科目群",
    "少人数教育科目群",
)
MISSING_LOCAL_FILE_VALUES = ("", "未保存", None)


def year_sort_value(value):
    match = re.match(r"^(\d{4})(前期|後期)?$", str(value))
    if not match:
        return (0, 0)
    semester_order = {"前期": 1, "後期": 2}
    return (int(match.group(1)), semester_order.get(match.group(2), 0))


def reverse_year_sort_value(value):
    year, semester = year_sort_value(value)
    return (-year, -semester)


def normalize_group(value):
    return value


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
        self.sort_var = tk.StringVar(value="年度が新しい順")
        self.status_var = tk.StringVar(value="準備中")
        self.local_file_var = tk.StringVar(value="ローカルファイル: 未選択")
        self.source_site_var = tk.StringVar(value="取得元: 未選択")
        self.notes_var = tk.StringVar(value="注釈: 未選択")
        self.feedback_summary_var = tk.StringVar(value="メモ: 未選択")

        self.ensure_data_store()
        self.create_widgets()
        self.create_context_menu()
        self.load_data()
        self.bind_events()
        self.clear_results("検索条件を指定して検索してください")

    def ensure_data_store(self):
        (ROOT / "data").mkdir(parents=True, exist_ok=True)
        FILES_DIR.mkdir(parents=True, exist_ok=True)

        seed_data_dir = SEED_ROOT / "data" if SEED_ROOT else None
        for name, default_content in (
            ("exams.json", "[]\n"),
            ("feedback.json", "[]\n"),
            ("kuwiki_unresolved.json", "[]\n"),
        ):
            target = ROOT / "data" / name
            if target.exists():
                continue
            seed = seed_data_dir / name if seed_data_dir else None
            if seed and seed.exists():
                shutil.copyfile(seed, target)
            else:
                target.write_text(default_content, encoding="utf-8")

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

        landing_button_frame = ttk.Frame(landing_panel)
        landing_button_frame.grid(row=12, column=0, sticky="ew", pady=(18, 0))
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

        button_frame = ttk.Frame(self.filter_frame)
        button_frame.grid(row=12, column=0, sticky="ew", pady=(18, 0))
        button_frame.columnconfigure(0, weight=1)
        ttk.Button(button_frame, text="条件をクリア", command=self.reset_filters).grid(row=0, column=0, sticky="ew")
        ttk.Button(button_frame, text="ホームへ", command=self.show_home).grid(row=1, column=0, sticky="ew", pady=(8, 0))

        self.main_frame = ttk.Frame(self, padding=(0, 16, 16, 16))
        self.main_frame.grid(row=0, column=1, sticky="nsew")
        self.main_frame.columnconfigure(0, weight=1)
        self.main_frame.rowconfigure(1, weight=1)

        toolbar = ttk.Frame(self.main_frame)
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        toolbar.columnconfigure(0, weight=1)

        self.count_label = ttk.Label(toolbar, text="0件", font=("", 16, "bold"))
        self.count_label.grid(row=0, column=0, sticky="w")
        ttk.Label(toolbar, text="並び替え").grid(row=0, column=1, sticky="e", padx=(12, 6))
        self.sort_combo = ttk.Combobox(
            toolbar,
            textvariable=self.sort_var,
            values=("年度が新しい順", "年度が古い順", "科目名順", "教師名順"),
            state="readonly",
            width=18,
        )
        self.sort_combo.grid(row=0, column=2, sticky="e")

        table_frame = ttk.Frame(self.main_frame)
        table_frame.grid(row=1, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)

        columns = ("year", "subject", "teacher", "group", "test_type", "source_site", "feedback_count")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")
        headings = {
            "year": "年度",
            "subject": "科目名",
            "teacher": "教師名",
            "group": "群",
            "test_type": "種別",
            "source_site": "取得元",
            "feedback_count": "メモ",
        }
        widths = {
            "year": 70,
            "subject": 150,
            "teacher": 130,
            "group": 80,
            "test_type": 95,
            "source_site": 110,
            "feedback_count": 70,
        }
        for column in columns:
            self.tree.heading(column, text=headings[column])
            self.tree.column(column, width=widths[column], minwidth=60, stretch=column == "subject")

        y_scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        x_scroll = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")

        footer_frame = ttk.Frame(self.main_frame)
        footer_frame.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        footer_frame.columnconfigure(4, weight=1)
        ttk.Button(footer_frame, text="詳細を表示", command=self.open_detail_page).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(footer_frame, text="ファイルの場所を開く", command=self.open_file_location).grid(row=0, column=1, padx=(0, 8))
        self.download_button = ttk.Button(footer_frame, text="Driveからローカル保存", command=self.download_selected, state="disabled")
        self.download_button.grid(row=0, column=2, padx=(0, 8))
        ttk.Button(footer_frame, text="ホームへ", command=self.show_home).grid(row=0, column=3, padx=(0, 8))
        ttk.Label(footer_frame, textvariable=self.status_var).grid(row=0, column=4, sticky="e")
        self.show_landing_layout()

    def create_context_menu(self):
        self.context_menu = tk.Menu(self, tearoff=False)
        self.context_menu.add_command(label="詳細を表示", command=self.open_detail_page)
        self.context_menu.add_command(label="ファイルの場所を開く", command=self.open_file_location)

    def add_labeled_entry(self, parent, label, variable, row):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w")
        entry = ttk.Entry(parent, textvariable=variable, width=28)
        entry.grid(row=row + 1, column=0, sticky="ew", pady=(4, 8))
        return entry

    def add_labeled_combo(self, parent, label, variable, row):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w")
        combo = ttk.Combobox(parent, textvariable=variable, state="readonly", width=26)
        combo.grid(row=row + 1, column=0, sticky="ew", pady=(4, 8))
        return combo

    def bind_events(self):
        self.tree.bind("<Double-1>", lambda _: self.open_preferred())
        self.tree.bind("<Button-2>", self.show_context_menu)
        self.tree.bind("<Button-3>", self.show_context_menu)
        self.tree.bind("<<TreeviewSelect>>", lambda _: self.update_selected_detail())
        self.landing_subject_entry.bind("<Return>", lambda _: self.apply_filters())
        self.landing_teacher_entry.bind("<Return>", lambda _: self.apply_filters())
        self.subject_query_var.trace_add("write", lambda *_: self.apply_filters_if_searched())
        self.teacher_query_var.trace_add("write", lambda *_: self.apply_filters_if_searched())
        for variable in (self.year_var, self.group_var, self.test_type_var):
            variable.trace_add("write", lambda *_: self.apply_filters_if_searched())
        self.sort_var.trace_add("write", lambda *_: self.apply_filters())

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
            DATA_PATH.write_text(json.dumps(self.exams, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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
        years = [""] + sorted(self.unique_values("year"), key=year_sort_value, reverse=True)
        groups = [""] + list(COURSE_GROUPS)
        test_types = [""] + list(TEST_TYPES)
        for combo in (self.year_combo, self.landing_year_combo):
            combo["values"] = years
        for combo in (self.group_combo, self.landing_group_combo):
            combo["values"] = groups
        for combo in (self.test_type_combo, self.landing_test_type_combo):
            combo["values"] = test_types

    def unique_values(self, field):
        return {exam.get(field, "") for exam in self.exams if exam.get(field)}

    def reset_filters(self):
        self.has_searched = False
        self.subject_query_var.set("")
        self.teacher_query_var.set("")
        self.year_var.set("")
        self.group_var.set("")
        self.test_type_var.set("")
        self.show_landing_layout()
        self.clear_results("検索条件を指定して検索してください")

    def show_home(self):
        self.has_searched = False
        self.show_landing_layout()
        self.clear_results("検索条件を指定して検索してください")

    def apply_filters(self):
        if not self.has_search_condition():
            self.clear_results("検索条件を1つ以上指定してください")
            return
        self.has_searched = True
        self.show_results_layout()
        self.filtered = [
            exam
            for exam in self.exams
            if self.matches(exam)
        ]
        self.filtered.sort(key=self.sort_key, reverse=self.sort_var.get() == "年度が新しい順")
        if self.sort_var.get() == "科目名順":
            self.filtered.sort(key=lambda exam: (exam.get("subject", ""), reverse_year_sort_value(exam.get("year", ""))))
        elif self.sort_var.get() == "教師名順":
            self.filtered.sort(key=lambda exam: (exam.get("teacher", ""), reverse_year_sort_value(exam.get("year", ""))))

        self.render_table()

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
        ))

    def clear_results(self, message):
        self.filtered = []
        self.tree.delete(*self.tree.get_children())
        self.count_label.config(text="0件")
        self.status_var.set(message)
        self.update_selected_detail()

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
        if self.year_var.get() and exam.get("year") != self.year_var.get():
            return False
        if self.group_var.get() and normalize_group(exam.get("group")) != self.group_var.get():
            return False
        if self.test_type_var.get() and exam.get("testType") != self.test_type_var.get():
            return False
        return True

    def sort_key(self, exam):
        return (year_sort_value(exam.get("year", "")), exam.get("subject", ""))

    def render_table(self):
        self.tree.delete(*self.tree.get_children())
        for exam in self.filtered:
            self.tree.insert(
                "",
                "end",
                iid=exam["id"],
                values=(
                    exam.get("year", ""),
                    exam.get("subject", ""),
                    exam.get("teacher", ""),
                    normalize_group(exam.get("group", "")),
                    exam.get("testType", ""),
                    exam.get("sourceSite", ""),
                    self.feedback_count(exam["id"]),
                ),
            )
        self.count_label.config(text=f"{len(self.filtered)}件")
        self.update_selected_detail()

    def selected_exam(self):
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("過去問検索", "過去問を選択してください。")
            return None
        exam_id = selection[0]
        return next((exam for exam in self.exams if exam.get("id") == exam_id), None)

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
        self.feedback_summary_var.set(self.feedback_summary(exam["id"]))
        self.download_button.configure(state="disabled" if local_file_exists(exam) else "normal")

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

    def feedback_for_exam(self, exam_id):
        return [item for item in self.feedback if item.get("examId") == exam_id and item.get("status", "open") == "open"]

    def feedback_count(self, exam_id):
        count = len(self.feedback_for_exam(exam_id))
        return "" if count == 0 else str(count)

    def feedback_summary(self, exam_id):
        items = self.feedback_for_exam(exam_id)
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
        window.geometry("560x620")
        window.minsize(520, 560)
        window.columnconfigure(0, weight=1)

        form = ttk.Frame(window, padding=16)
        form.grid(row=0, column=0, sticky="nsew")
        form.columnconfigure(1, weight=1)

        values = {
            "file": tk.StringVar(),
            "year": tk.StringVar(),
            "teacher": tk.StringVar(),
            "subject": tk.StringVar(),
            "group": tk.StringVar(),
            "testType": tk.StringVar(value="定期テスト"),
            "sourceSite": tk.StringVar(value="手動追加"),
            "driveUrl": tk.StringVar(),
        }

        ttk.Label(form, text="過去問を追加", font=("", 20, "bold")).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 14))
        self.add_form_row(form, "ファイル", values["file"], 1, browse_command=lambda: self.choose_exam_file(values["file"]))
        self.add_form_row(form, "年度", values["year"], 2)
        self.add_form_row(form, "教師名", values["teacher"], 3)
        self.add_form_row(form, "科目名", values["subject"], 4)
        self.add_form_combo(form, "科目群", values["group"], 5, COURSE_GROUPS)
        self.add_form_combo(form, "テスト種別", values["testType"], 6, TEST_TYPES)
        self.add_form_row(form, "取得元", values["sourceSite"], 7)
        self.add_form_row(form, "Drive URL", values["driveUrl"], 8)

        ttk.Label(form, text="注釈").grid(row=9, column=0, sticky="nw", padx=(0, 10), pady=(8, 4))
        notes = tk.Text(form, height=5, wrap="word", relief="solid", borderwidth=1, padx=8, pady=8)
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
        ttk.Button(button_frame, text="キャンセル", command=window.destroy).grid(row=0, column=1, sticky="ew", padx=(6, 0))

    def add_form_row(self, parent, label, variable, row, browse_command=None):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=5)
        entry = ttk.Entry(parent, textvariable=variable)
        entry.grid(row=row, column=1, sticky="ew", pady=5)
        if browse_command:
            ttk.Button(parent, text="選択", command=browse_command).grid(row=row, column=2, sticky="ew", padx=(8, 0), pady=5)
        else:
            ttk.Label(parent, text="").grid(row=row, column=2, sticky="ew", padx=(8, 0), pady=5)

    def add_form_combo(self, parent, label, variable, row, values):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=5)
        combo = ttk.Combobox(parent, textvariable=variable, values=values, state="readonly")
        combo.grid(row=row, column=1, columnspan=2, sticky="ew", pady=5)

    def choose_exam_file(self, file_var):
        filename = filedialog.askopenfilename(title="追加する過去問ファイルを選択")
        if filename:
            file_var.set(filename)

    def add_exam(self, values, notes_widget, window):
        year = values["year"].get().strip()
        subject = values["subject"].get().strip()
        group = values["group"].get().strip()
        test_type = values["testType"].get().strip()
        file_path = values["file"].get().strip()
        drive_url = values["driveUrl"].get().strip()

        if not year or not subject or not group or not test_type:
            messagebox.showinfo("過去問検索", "年度、科目名、科目群、テスト種別は必須です。")
            return
        if not file_path and not drive_url:
            messagebox.showinfo("過去問検索", "ファイルまたはDrive URLを指定してください。")
            return

        local_file = ""
        if file_path:
            source = Path(file_path)
            if not source.exists():
                messagebox.showwarning("過去問検索", f"ファイルが見つかりません。\n{source}")
                return
            FILES_DIR.mkdir(parents=True, exist_ok=True)
            target_name = "_".join(safe_filename_part(part) for part in (year, subject, values["teacher"].get(), test_type) if part)
            target = unique_file_path(FILES_DIR / f"{target_name or safe_filename_part(source.stem)}{source.suffix}")
            shutil.copyfile(source, target)
            local_file = f"./files/{target.name}"

        now = datetime.now().strftime("%Y%m%d%H%M%S")
        exam = {
            "id": f"manual-{now}-{safe_filename_part(subject)}",
            "year": year,
            "teacher": values["teacher"].get().strip(),
            "subject": subject,
            "group": group,
            "testType": test_type,
            "sourceSite": values["sourceSite"].get().strip() or "手動追加",
            "localFile": local_file,
            "driveUrl": drive_url,
            "notes": notes_widget.get("1.0", "end").strip(),
        }
        self.exams.append(exam)
        DATA_PATH.write_text(json.dumps(self.exams, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.refresh_filter_options()
        if self.has_searched:
            self.apply_filters()
        self.status_var.set("過去問を追加しました")
        messagebox.showinfo("過去問検索", "過去問を追加しました。")
        window.destroy()

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
        rows = (
            ("年度", exam.get("year", "")),
            ("教師名", exam.get("teacher", "") or "未設定"),
            ("科目名", exam.get("subject", "") or "未設定"),
            ("科目群", exam.get("group", "") or "未設定"),
            ("テスト種別", exam.get("testType", "") or "未設定"),
            ("取得元", exam.get("sourceSite", "") or "未設定"),
            ("ファイル状態", "ローカル保存済み" if local_file_exists(exam) else "Drive参照" if exam.get("driveUrl") else "未登録"),
            ("ローカルファイル", exam.get("localFile") if local_file_exists(exam) else "なし"),
            ("注釈", exam.get("notes", "") or "なし"),
        )
        for row, (label, value) in enumerate(rows):
            ttk.Label(info, text=label).grid(row=row, column=0, sticky="nw", padx=(0, 12), pady=3)
            ttk.Label(info, text=value, wraplength=560).grid(row=row, column=1, sticky="ew", pady=3)

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
        existing.insert("1.0", self.detail_feedback_text(exam["id"]))
        existing.configure(state="disabled")

        ttk.Label(feedback_box, text="新しいメモ").grid(row=1, column=0, sticky="w", pady=(10, 4))
        new_feedback = tk.Text(feedback_box, height=4, wrap="word", relief="solid", borderwidth=1, padx=8, pady=8)
        new_feedback.grid(row=2, column=0, sticky="ew")
        ttk.Button(
            feedback_box,
            text="メモを保存",
            command=lambda: self.save_detail_feedback(exam, new_feedback, existing),
        ).grid(row=2, column=1, sticky="ns", padx=(10, 0))

        actions = ttk.Frame(window, padding=(16, 0, 16, 16))
        actions.grid(row=2, column=0, sticky="ew")
        actions.columnconfigure(4, weight=1)
        ttk.Button(actions, text="開く", command=lambda: self.open_exam_preferred(exam)).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(actions, text="ファイルの場所を開く", command=lambda: self.open_exam_file_location(exam)).grid(row=0, column=1, padx=(0, 8))
        download_state = "disabled" if local_file_exists(exam) else "normal"
        ttk.Button(
            actions,
            text="Driveからローカル保存",
            command=lambda: self.download_exam_from_detail(exam, window),
            state=download_state,
        ).grid(row=0, column=2, padx=(0, 8))
        ttk.Button(actions, text="閉じる", command=window.destroy).grid(row=0, column=3, padx=(0, 8))

    def detail_feedback_text(self, exam_id):
        items = self.feedback_for_exam(exam_id)
        if not items:
            return "メモはまだありません。"
        lines = []
        for item in items:
            lines.append(f"[{item.get('createdAt', '')}] {item.get('comment', '')}")
        return "\n\n".join(lines)

    def save_detail_feedback(self, exam, text_widget, existing_widget):
        comment = text_widget.get("1.0", "end").strip()
        if not comment:
            messagebox.showinfo("過去問検索", "保存するメモを入力してください。")
            return
        self.add_feedback(exam, comment)
        text_widget.delete("1.0", "end")
        existing_widget.configure(state="normal")
        existing_widget.delete("1.0", "end")
        existing_widget.insert("1.0", self.detail_feedback_text(exam["id"]))
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
                "sourceSite": exam.get("sourceSite", ""),
            },
        })
        self.write_feedback()

    def open_exam_preferred(self, exam):
        if local_file_exists(exam):
            self.open_path(exam["localFile"])
        elif exam.get("driveUrl"):
            webbrowser.open(exam["driveUrl"])
        else:
            messagebox.showinfo("過去問検索", "ファイルもDriveリンクも登録されていません。")

    def open_exam_file_location(self, exam):
        if local_file_exists(exam):
            self.open_path_location(exam["localFile"])
        elif exam.get("driveUrl"):
            webbrowser.open(exam["driveUrl"])
        else:
            messagebox.showinfo("過去問検索", "ファイルもDriveリンクも登録されていません。")

    def download_exam_from_detail(self, exam, window):
        if local_file_exists(exam):
            messagebox.showinfo("過去問検索", "すでにローカルに保存されています。")
            return
        if not exam.get("driveUrl"):
            messagebox.showinfo("過去問検索", "Google Driveリンクが登録されていません。")
            return
        self.status_var.set("Driveから保存中...")
        thread = threading.Thread(target=self.download_detail_worker, args=(exam["id"], window), daemon=True)
        thread.start()

    def download_detail_worker(self, exam_id, window):
        try:
            result = download_exam_file(exam_id)
            self.after(0, lambda: self.finish_detail_download(result["localFile"], window))
        except Exception as error:
            self.after(0, lambda: self.fail_download(str(error)))

    def finish_detail_download(self, local_file, window):
        self.load_data()
        self.apply_filters()
        self.status_var.set("保存しました")
        messagebox.showinfo("過去問検索", f"ローカルに保存しました。\n{local_file}")
        window.destroy()

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
        exam = self.selected_exam()
        if not exam:
            return
        if local_file_exists(exam):
            messagebox.showinfo("過去問検索", "すでにローカルに保存されています。")
            return
        if not exam.get("driveUrl"):
            messagebox.showinfo("過去問検索", "Google Driveリンクが登録されていません。")
            return

        self.status_var.set("Driveから保存中...")
        thread = threading.Thread(target=self.download_worker, args=(exam["id"],), daemon=True)
        thread.start()

    def download_worker(self, exam_id):
        try:
            result = download_exam_file(exam_id)
            self.after(0, lambda: self.finish_download(result["localFile"]))
        except Exception as error:
            self.after(0, lambda: self.fail_download(str(error)))

    def finish_download(self, local_file):
        self.load_data()
        self.apply_filters()
        self.status_var.set("保存しました")
        messagebox.showinfo("過去問検索", f"ローカルに保存しました。\n{local_file}")

    def fail_download(self, message):
        self.status_var.set("保存に失敗しました")
        messagebox.showerror("過去問検索", f"Driveから保存できませんでした。\n{message}")


if __name__ == "__main__":
    app = KakomonApp()
    app.mainloop()
