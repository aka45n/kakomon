#!/usr/bin/env python3
"""Small tkinter application for searching the 2026 syllabus."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from syllabus_search import SyllabusSearchEngine, record_year


ALL_YEARS_LABEL = "全年度"
DETAIL_FIELDS = (
    "授業科目名",
    "担当者名",
    "年度",
    "配当学年",
    "開講期",
    "曜時限",
    "群",
    "学科",
    "前身科目",
)


class SyllabusSearchApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("シラバス検索")
        self.root.geometry("940x650")
        self.root.minsize(760, 560)

        self.style = ttk.Style()
        if "clam" in self.style.theme_names():
            self.style.theme_use("clam")
        self.style.configure(
            "TButton",
            background="#ffffff",
            foreground="#16181d",
            bordercolor="#d8dde5",
            padding=(8, 5),
        )
        self.style.map(
            "TButton",
            background=[("active", "#fff4e8"), ("pressed", "#f9e1c7")],
            foreground=[("active", "#16181d"), ("pressed", "#16181d")],
        )
        self.style.configure(
            "TScrollbar",
            background="#eef1f4",
            troughcolor="#ffffff",
            bordercolor="#ffffff",
            arrowcolor="#596273",
        )
        self.style.configure(
            "Treeview",
            background="#ffffff",
            fieldbackground="#ffffff",
            foreground="#111827",
            rowheight=27,
            borderwidth=0,
        )
        self.style.configure(
            "Treeview.Heading",
            background="#f2f4f7",
            foreground="#111827",
            bordercolor="#c9d0da",
            lightcolor="#c9d0da",
            darkcolor="#c9d0da",
            relief="solid",
        )
        self.style.map(
            "Treeview",
            background=[("selected", "#cfe0f7")],
            foreground=[("selected", "#111827")],
        )
        self.root.configure(background="#ffffff")

        try:
            self.engine = SyllabusSearchEngine.from_json()
        except (OSError, ValueError) as exc:
            messagebox.showerror("読み込みエラー", f"シラバスデータを読み込めませんでした。\n{exc}")
            raise

        self.query = tk.StringVar()
        self.selected_year = tk.StringVar(value=ALL_YEARS_LABEL)
        self.status = tk.StringVar(value=f"全 {len(self.engine.records):,} 件")
        self.result_query = tk.StringVar()
        self.detail_values = {field: tk.StringVar(value="-") for field in DETAIL_FIELDS}
        self.visible_records: list[dict[str, str]] = []
        self.hovered_suggestion: int | None = None

        self._build_ui()
        self.query.trace_add("write", self._on_query_changed)

    def _build_ui(self) -> None:
        self.page_container = tk.Frame(self.root, background="#ffffff")
        self.page_container.pack(fill="both", expand=True)
        self.search_page = tk.Frame(self.page_container, background="#ffffff")
        self.results_page = tk.Frame(self.page_container, background="#ffffff", padx=20, pady=20)
        self.search_page.columnconfigure(0, weight=1)
        self.search_page.rowconfigure(0, weight=1)

        search_content = tk.Frame(
            self.search_page,
            background="#ffffff",
        )
        search_content.grid(row=0, column=0, padx=40, pady=(110, 0), sticky="n")
        header_row = tk.Frame(search_content, width=400, height=38, background="#ffffff")
        header_row.pack(fill="x", pady=(0, 30))
        header_row.pack_propagate(False)
        tk.Label(
            header_row,
            text="シラバス検索",
            background="#ffffff",
            foreground="#16181d",
            font=("TkDefaultFont", 28, "bold"),
        ).place(relx=0.5, rely=0.5, anchor="center")
        year_row = tk.Frame(search_content, background="#ffffff")
        self.year_choices = [ALL_YEARS_LABEL, *self.engine.years]
        self.year_selector = tk.Canvas(
            year_row,
            width=86,
            height=24,
            background="#ffffff",
            highlightthickness=0,
            borderwidth=0,
            cursor="hand2",
        )
        self.year_selector.pack(side="right")
        self._rounded_rectangle(
            self.year_selector,
            1,
            1,
            85,
            23,
            radius=8,
            fill="#ffffff",
            outline="#d98a3a",
            width=2,
        )
        self.year_selector_text = self.year_selector.create_text(
            36,
            11,
            text=self.selected_year.get(),
            fill="#16181d",
            font=("TkDefaultFont", 11),
        )
        self.year_selector.create_polygon(68, 10, 74, 10, 71, 14, fill="#a85f19", outline="")
        self.year_menu = tk.Menu(self.root, tearoff=False, font=("TkDefaultFont", 10))
        for year in self.year_choices:
            self.year_menu.add_command(
                label=f"  {year}  ",
                command=lambda selected=year: self._select_year(selected),
            )
        self.year_selector.bind("<Button-1>", self._show_year_menu)
        year_row.pack(fill="x", pady=(0, 10))
        self.search_canvas = tk.Canvas(
            search_content,
            width=400,
            height=54,
            background="#ffffff",
            highlightthickness=0,
            borderwidth=0,
        )
        self.search_canvas.pack()
        self.search_border = self._rounded_rectangle(
            self.search_canvas,
            1,
            1,
            399,
            53,
            radius=16,
            fill="#ffffff",
            outline="#d98a3a",
            width=1,
        )
        self.search_entry = tk.Entry(
            self.search_canvas,
            textvariable=self.query,
            font=("TkDefaultFont", 16),
            background="#ffffff",
            foreground="#16181d",
            insertbackground="#16181d",
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
        )
        self.search_canvas.create_window(18, 11, window=self.search_entry, width=364, height=32, anchor="nw")
        self.search_entry.bind("<Return>", self._run_search)
        self.search_entry.bind("<FocusIn>", self._on_search_focus_in)
        self.search_entry.bind("<FocusOut>", self._on_search_focus_out)
        self.placeholder_label = tk.Label(
            self.search_canvas,
            text="科目名",
            background="#ffffff",
            foreground="#9ca3af",
            font=("TkDefaultFont", 16),
            cursor="xterm",
        )
        self.placeholder_window = self.search_canvas.create_window(
            20,
            27,
            window=self.placeholder_label,
            anchor="w",
        )
        self.placeholder_label.bind("<Button-1>", self._focus_search_entry)
        self.suggestion_box = tk.Listbox(
            search_content,
            height=0,
            width=1,
            activestyle="none",
            exportselection=False,
            background="#ffffff",
            foreground="#16181d",
            font=("TkDefaultFont", 14),
            borderwidth=0,
            highlightthickness=0,
            selectbackground="#dde5f0",
            selectforeground="#16181d",
            selectborderwidth=1,
            cursor="hand2",
        )
        self.suggestion_box.bind("<<ListboxSelect>>", self._choose_suggestion)
        self.suggestion_box.bind("<Return>", self._choose_suggestion)
        self.suggestion_box.bind("<Motion>", self._hover_suggestion)
        self.suggestion_box.bind("<Leave>", self._clear_suggestion_hover)

        self.result_header = tk.Frame(self.results_page, background="#ffffff")
        self.result_header.pack(fill="x", pady=(2, 8))
        ttk.Button(self.result_header, text="← 検索へ戻る", command=self._show_search_page).pack(side="left")
        tk.Label(
            self.result_header,
            text="検索結果",
            background="#ffffff",
            foreground="#111827",
            font=("TkDefaultFont", 18, "bold"),
        ).pack(side="left", padx=(14, 0))
        tk.Label(
            self.result_header,
            textvariable=self.status,
            background="#ffffff",
            foreground="#111827",
        ).pack(side="right")
        tk.Label(
            self.results_page,
            textvariable=self.result_query,
            background="#ffffff",
            foreground="#374151",
        ).pack(anchor="w", pady=(0, 6))

        content_pane = tk.PanedWindow(
            self.results_page,
            orient="vertical",
            background="#ffffff",
            borderwidth=0,
            sashwidth=7,
            sashrelief="flat",
            showhandle=False,
        )
        content_pane.pack(fill="both", expand=True)

        columns = ("subject", "teacher", "group", "year", "term")
        result_frame = tk.Frame(
            content_pane,
            background="#ffffff",
            padx=1,
            pady=1,
            highlightbackground="#c9d0da",
            highlightthickness=1,
        )
        self.results = ttk.Treeview(result_frame, columns=columns, show="headings", height=12)
        self.results.heading("subject", text="科目名")
        self.results.heading("teacher", text="教師")
        self.results.heading("group", text="群")
        self.results.heading("year", text="年度")
        self.results.heading("term", text="開講期")
        self.results.column("subject", width=350, minwidth=220)
        self.results.column("teacher", width=260, minwidth=160)
        self.results.column("group", width=140, minwidth=100)
        self.results.column("year", width=65, minwidth=55, anchor="center")
        self.results.column("term", width=90, minwidth=70, anchor="center")
        scrollbar = ttk.Scrollbar(result_frame, orient="vertical", command=self.results.yview)
        self.results.configure(yscrollcommand=scrollbar.set)
        self.results.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.results.bind("<<TreeviewSelect>>", self._show_detail)
        content_pane.add(result_frame, minsize=150, stretch="always")

        detail = tk.Frame(
            content_pane,
            background="#ffffff",
            padx=14,
            pady=12,
            highlightbackground="#c9d0da",
            highlightthickness=1,
        )
        tk.Label(
            detail,
            text="シラバス詳細",
            background="#ffffff",
            foreground="#16181d",
            font=("TkDefaultFont", 12, "bold"),
        ).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 8))
        for index, field in enumerate(DETAIL_FIELDS):
            row, column = divmod(index, 2)
            row += 1
            label_column = column * 2
            tk.Label(
                detail,
                text=field,
                width=10,
                anchor="nw",
                background="#ffffff",
                foreground="#5b6472",
            ).grid(row=row, column=label_column, sticky="nw", pady=3)
            tk.Label(
                detail,
                textvariable=self.detail_values[field],
                wraplength=340,
                justify="left",
                anchor="nw",
                background="#ffffff",
                foreground="#16181d",
            ).grid(row=row, column=label_column + 1, sticky="nw", padx=(0, 18), pady=3)
        detail.columnconfigure(1, weight=1)
        detail.columnconfigure(3, weight=1)
        content_pane.add(detail, minsize=205, stretch="never")
        self._show_page(self.search_page)

    @staticmethod
    def _rounded_rectangle(canvas, x1, y1, x2, y2, radius, **options):
        points = (
            x1 + radius, y1,
            x2 - radius, y1,
            x2, y1,
            x2, y1 + radius,
            x2, y2 - radius,
            x2, y2,
            x2 - radius, y2,
            x1 + radius, y2,
            x1, y2,
            x1, y2 - radius,
            x1, y1 + radius,
            x1, y1,
        )
        return canvas.create_polygon(points, smooth=True, splinesteps=36, **options)

    def _focus_search_entry(self, _event=None) -> None:
        self.search_entry.focus_set()

    def _on_search_focus_in(self, _event=None) -> None:
        self.search_canvas.itemconfigure(self.search_border, outline="#c96f18", width=2)
        self.search_canvas.itemconfigure(self.placeholder_window, state="hidden")

    def _on_search_focus_out(self, _event=None) -> None:
        self.search_canvas.itemconfigure(self.search_border, outline="#d98a3a", width=1)
        if not self.query.get():
            self.search_canvas.itemconfigure(self.placeholder_window, state="normal")

    def _show_page(self, page: tk.Frame) -> None:
        self.search_page.pack_forget()
        self.results_page.pack_forget()
        page.pack(fill="both", expand=True)

    def _show_search_page(self) -> None:
        self._show_page(self.search_page)
        self.search_entry.focus_set()

    def _on_query_changed(self, *_args) -> None:
        self.search_canvas.itemconfigure(
            self.placeholder_window,
            state="hidden" if self.query.get() else "normal",
        )
        suggestions = self.engine.suggestions(self.query.get(), year=self._selected_year_filter())
        self._clear_suggestion_hover()
        self.suggestion_box.delete(0, "end")
        if not suggestions:
            self.suggestion_box.pack_forget()
            return
        for title in suggestions:
            self.suggestion_box.insert("end", title)
        self.suggestion_box.configure(height=min(len(suggestions), 8))
        self.suggestion_box.pack(fill="x", pady=(8, 0))

    def _hover_suggestion(self, event) -> None:
        if not self.suggestion_box.size():
            return
        index = self.suggestion_box.nearest(event.y)
        bounds = self.suggestion_box.bbox(index)
        if not bounds or not (bounds[1] <= event.y < bounds[1] + bounds[3]):
            self._clear_suggestion_hover()
            return
        if self.hovered_suggestion == index:
            return
        self._clear_suggestion_hover()
        self.suggestion_box.itemconfigure(index, foreground="#c96f18")
        self.hovered_suggestion = index

    def _clear_suggestion_hover(self, _event=None) -> None:
        if self.hovered_suggestion is not None and self.hovered_suggestion < self.suggestion_box.size():
            self.suggestion_box.itemconfigure(self.hovered_suggestion, foreground="#16181d")
        self.hovered_suggestion = None

    def _choose_suggestion(self, _event=None) -> None:
        selection = self.suggestion_box.curselection()
        if not selection:
            return
        self.query.set(self.suggestion_box.get(selection[0]))
        self.suggestion_box.pack_forget()
        self._run_search()

    def _on_year_changed(self, _event=None) -> None:
        self._on_query_changed()

    def _select_year(self, year: str) -> None:
        self.selected_year.set(year)
        self.year_selector.itemconfigure(self.year_selector_text, text=year)
        self._on_year_changed()

    def _show_year_menu(self, _event=None) -> None:
        x = self.year_selector.winfo_rootx()
        y = self.year_selector.winfo_rooty() + self.year_selector.winfo_height()
        try:
            self.year_menu.tk_popup(x, y)
        finally:
            self.year_menu.grab_release()

    def _selected_year_filter(self) -> str | None:
        year = self.selected_year.get()
        return None if year == ALL_YEARS_LABEL else year

    def _run_search(self, _event=None) -> None:
        query = self.query.get().strip()
        self.suggestion_box.pack_forget()
        self.visible_records = self.engine.search(query, year=self._selected_year_filter())
        self.results.delete(*self.results.get_children())
        for index, record in enumerate(self.visible_records):
            self.results.insert(
                "",
                "end",
                iid=str(index),
                values=(
                    record.get("授業科目名", ""),
                    record.get("担当者名", ""),
                    record.get("群", ""),
                    record_year(record),
                    record.get("開講期", ""),
                ),
            )
        self.status.set(f"{len(self.visible_records):,} 件ヒット" if query else f"全 {len(self.engine.records):,} 件")
        year_label = self.selected_year.get()
        prefix = "全年度" if year_label == ALL_YEARS_LABEL else f"{year_label}年度"
        self.result_query.set(f"{prefix}「{query}」の検索結果")
        self._clear_detail()
        self._show_page(self.results_page)

    def _show_detail(self, _event=None) -> None:
        selection = self.results.selection()
        if not selection:
            return
        record = self.visible_records[int(selection[0])]
        for field in DETAIL_FIELDS:
            value = record_year(record) if field == "年度" else record.get(field, "")
            self.detail_values[field].set(value or "-")

    def _clear_detail(self) -> None:
        for value in self.detail_values.values():
            value.set("-")


def main() -> None:
    root = tk.Tk()
    SyllabusSearchApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
