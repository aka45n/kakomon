from pathlib import Path
import json
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk
import webbrowser

from drive_downloader import DATA_PATH, ROOT, download_exam_file


TEST_TYPES = ("小テスト", "定期テスト")


class KakomonApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("過去問検索")
        self.geometry("1120x700")
        self.minsize(900, 560)

        self.exams = []
        self.filtered = []
        self.keyword_var = tk.StringVar()
        self.year_var = tk.StringVar()
        self.teacher_var = tk.StringVar()
        self.subject_var = tk.StringVar()
        self.group_var = tk.StringVar()
        self.sort_var = tk.StringVar(value="年度が新しい順")
        self.test_type_vars = {test_type: tk.BooleanVar(value=False) for test_type in TEST_TYPES}
        self.status_var = tk.StringVar(value="準備中")
        self.local_file_var = tk.StringVar(value="ローカルファイル: 未選択")
        self.source_site_var = tk.StringVar(value="取得元: 未選択")
        self.notes_var = tk.StringVar(value="注釈: 未選択")

        self.create_widgets()
        self.load_data()
        self.bind_events()
        self.apply_filters()

    def create_widgets(self):
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        filter_frame = ttk.Frame(self, padding=16)
        filter_frame.grid(row=0, column=0, sticky="ns")
        filter_frame.columnconfigure(0, weight=1)

        ttk.Label(filter_frame, text="過去問検索", font=("", 22, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(filter_frame, text="年度・教師名・科目名・群で絞り込み").grid(row=1, column=0, sticky="w", pady=(4, 18))

        self.keyword_entry = self.add_labeled_entry(filter_frame, "キーワード", self.keyword_var, 2)
        self.year_combo = self.add_labeled_combo(filter_frame, "年度", self.year_var, 4)
        self.teacher_combo = self.add_labeled_combo(filter_frame, "教師名", self.teacher_var, 6)
        self.subject_combo = self.add_labeled_combo(filter_frame, "科目名", self.subject_var, 8)
        self.group_combo = self.add_labeled_combo(filter_frame, "群", self.group_var, 10)

        ttk.Label(filter_frame, text="テスト種別").grid(row=12, column=0, sticky="w", pady=(12, 4))
        type_frame = ttk.Frame(filter_frame)
        type_frame.grid(row=13, column=0, sticky="ew")
        for index, test_type in enumerate(TEST_TYPES):
            ttk.Checkbutton(type_frame, text=test_type, variable=self.test_type_vars[test_type]).grid(
                row=index, column=0, sticky="w", pady=2
            )

        ttk.Button(filter_frame, text="条件をクリア", command=self.reset_filters).grid(row=14, column=0, sticky="ew", pady=(18, 0))

        main_frame = ttk.Frame(self, padding=(0, 16, 16, 16))
        main_frame.grid(row=0, column=1, sticky="nsew")
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(1, weight=1)

        toolbar = ttk.Frame(main_frame)
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

        table_frame = ttk.Frame(main_frame)
        table_frame.grid(row=1, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)

        columns = ("year", "subject", "teacher", "group", "test_type", "source_site", "file_state", "notes")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")
        headings = {
            "year": "年度",
            "subject": "科目名",
            "teacher": "教師名",
            "group": "群",
            "test_type": "種別",
            "source_site": "取得元",
            "file_state": "ファイル",
            "notes": "注釈",
        }
        widths = {
            "year": 70,
            "subject": 150,
            "teacher": 130,
            "group": 80,
            "test_type": 95,
            "source_site": 110,
            "file_state": 130,
            "notes": 220,
        }
        for column in columns:
            self.tree.heading(column, text=headings[column])
            self.tree.column(column, width=widths[column], minwidth=60, stretch=column == "notes")

        y_scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        x_scroll = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")

        action_frame = ttk.Frame(main_frame)
        action_frame.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        action_frame.columnconfigure(4, weight=1)

        ttk.Button(action_frame, text="開く", command=self.open_preferred).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(action_frame, text="ローカルファイルを開く", command=self.open_local_file).grid(row=0, column=1, padx=(0, 8))
        ttk.Button(action_frame, text="Driveを参照", command=self.open_drive).grid(row=0, column=2, padx=(0, 8))
        ttk.Button(action_frame, text="Driveからローカル保存", command=self.download_selected).grid(row=0, column=3, padx=(0, 8))
        ttk.Label(action_frame, textvariable=self.status_var).grid(row=0, column=4, sticky="e")

        detail_frame = ttk.LabelFrame(main_frame, text="選択中の参照先", padding=10)
        detail_frame.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        detail_frame.columnconfigure(0, weight=1)
        ttk.Label(detail_frame, textvariable=self.local_file_var, wraplength=760).grid(row=0, column=0, sticky="w")
        ttk.Label(detail_frame, textvariable=self.source_site_var, wraplength=760).grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Label(detail_frame, textvariable=self.notes_var, wraplength=760).grid(row=2, column=0, sticky="w", pady=(4, 0))

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
        self.keyword_var.trace_add("write", lambda *_: self.apply_filters())
        for variable in (self.year_var, self.teacher_var, self.subject_var, self.group_var, self.sort_var):
            variable.trace_add("write", lambda *_: self.apply_filters())
        for variable in self.test_type_vars.values():
            variable.trace_add("write", lambda *_: self.apply_filters())
        self.tree.bind("<Double-1>", lambda _: self.open_preferred())
        self.tree.bind("<<TreeviewSelect>>", lambda _: self.update_selected_detail())

    def load_data(self):
        self.exams = json.loads(DATA_PATH.read_text(encoding="utf-8"))
        self.refresh_filter_options()
        self.status_var.set("データを読み込みました")

    def refresh_filter_options(self):
        self.year_combo["values"] = [""] + sorted(self.unique_values("year"), key=lambda value: int(value), reverse=True)
        self.teacher_combo["values"] = [""] + sorted(self.unique_values("teacher"))
        self.subject_combo["values"] = [""] + sorted(self.unique_values("subject"))
        self.group_combo["values"] = [""] + sorted(self.unique_values("group"))

    def unique_values(self, field):
        return {exam.get(field, "") for exam in self.exams if exam.get(field)}

    def reset_filters(self):
        self.keyword_var.set("")
        self.year_var.set("")
        self.teacher_var.set("")
        self.subject_var.set("")
        self.group_var.set("")
        for variable in self.test_type_vars.values():
            variable.set(False)

    def apply_filters(self):
        keyword = self.keyword_var.get().strip().lower()
        selected_types = {test_type for test_type, variable in self.test_type_vars.items() if variable.get()}

        self.filtered = [
            exam
            for exam in self.exams
            if self.matches(exam, keyword, selected_types)
        ]
        self.filtered.sort(key=self.sort_key, reverse=self.sort_var.get() == "年度が新しい順")
        if self.sort_var.get() == "科目名順":
            self.filtered.sort(key=lambda exam: (exam.get("subject", ""), -int(exam.get("year", 0))))
        elif self.sort_var.get() == "教師名順":
            self.filtered.sort(key=lambda exam: (exam.get("teacher", ""), -int(exam.get("year", 0))))

        self.render_table()

    def matches(self, exam, keyword, selected_types):
        if self.year_var.get() and exam.get("year") != self.year_var.get():
            return False
        if self.teacher_var.get() and exam.get("teacher") != self.teacher_var.get():
            return False
        if self.subject_var.get() and exam.get("subject") != self.subject_var.get():
            return False
        if self.group_var.get() and exam.get("group") != self.group_var.get():
            return False
        if selected_types and exam.get("testType") not in selected_types:
            return False
        if keyword and keyword not in self.search_text(exam):
            return False
        return True

    def search_text(self, exam):
        return " ".join(str(exam.get(field, "")) for field in (
            "year",
            "teacher",
            "subject",
            "group",
            "testType",
            "localFile",
            "notes",
        )).lower()

    def sort_key(self, exam):
        try:
            year = int(exam.get("year", 0))
        except ValueError:
            year = 0
        return (year, exam.get("subject", ""))

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
                    exam.get("group", ""),
                    exam.get("testType", ""),
                    exam.get("sourceSite", ""),
                    "ローカル保存済み" if exam.get("localFile") else "Drive参照" if exam.get("driveUrl") else "未登録",
                    exam.get("notes", ""),
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
            return

        exam = next((item for item in self.exams if item.get("id") == selection[0]), None)
        if not exam:
            return

        local_file = exam.get("localFile") or "なし"
        source_site = exam.get("sourceSite") or "なし"
        notes = exam.get("notes") or "なし"
        self.local_file_var.set(f"ローカルファイル: {local_file}")
        self.source_site_var.set(f"取得元: {source_site}")
        self.notes_var.set(f"注釈: {notes}")

    def open_preferred(self):
        exam = self.selected_exam()
        if not exam:
            return
        if exam.get("localFile"):
            self.open_path(exam["localFile"])
        elif exam.get("driveUrl"):
            webbrowser.open(exam["driveUrl"])
        else:
            messagebox.showinfo("過去問検索", "ファイルもDriveリンクも登録されていません。")

    def open_local_file(self):
        exam = self.selected_exam()
        if exam and exam.get("localFile"):
            self.open_path(exam["localFile"])
        elif exam:
            messagebox.showinfo("過去問検索", "ローカルファイルは未保存です。")

    def open_drive(self):
        exam = self.selected_exam()
        if exam and exam.get("driveUrl"):
            webbrowser.open(exam["driveUrl"])
        elif exam:
            messagebox.showinfo("過去問検索", "Google Driveリンクが登録されていません。")

    def open_path(self, path):
        full_path = (ROOT / path).resolve() if not Path(path).is_absolute() else Path(path)
        if not full_path.exists():
            messagebox.showwarning("過去問検索", f"ファイルが見つかりません。\n{full_path}")
            return
        if sys.platform == "darwin":
            subprocess.run(["open", str(full_path)], check=False)
        elif sys.platform.startswith("win"):
            subprocess.run(["cmd", "/c", "start", "", str(full_path)], check=False)
        else:
            subprocess.run(["xdg-open", str(full_path)], check=False)

    def download_selected(self):
        exam = self.selected_exam()
        if not exam:
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
