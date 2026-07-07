# Developer File Rules

This file is the short context for coding agents. Prefer it over reading the full README when you only need repository layout and edit rules.

## Main Files

- `desktop_app.py`: Main tkinter app. Search UI, filters, dialogs, feedback memos, edit/delete flows.
- `drive_downloader.py`: Google Drive download and local filename generation.
- `data/exams.json`: Main exam metadata.
- `data/feedback.json`: Open correction memos created in the app.
- `scripts/import_kuwiki.py`: 京大wiki importer.
- `scripts/import_ku1025.py`: KU1025 importer.
- `data/ku1025_unresolved.json`: KU1025 items the importer could not confidently turn into exam records.
- `過去問検索.app/Contents/Resources/`: Bundled app copy of runtime files.

## Mirror Rule

When editing these root files, apply the same change to the bundled app copy:

- `desktop_app.py`
- `drive_downloader.py`
- `data/exams.json`
- `data/feedback.json`, only when intentionally changing bundled seed feedback

Bundled paths:

- `過去問検索.app/Contents/Resources/desktop_app.py`
- `過去問検索.app/Contents/Resources/drive_downloader.py`
- `過去問検索.app/Contents/Resources/data/exams.json`
- `過去問検索.app/Contents/Resources/data/feedback.json`

## User Data

Finder-launched app data lives outside the repo:

```text
~/Library/Application Support/Kakomon/data/exams.json
~/Library/Application Support/Kakomon/data/feedback.json
~/Library/Application Support/Kakomon/files/
```

The app copies bundled seed data on first launch and later merges missing bundled exam IDs into existing user data. Do not assume editing repo `data/exams.json` alone updates an already-created user data store until the app launches and merges.

## Naming Rules

- Manual upload filenames stay in the old local rule and do not include source site.
- Drive-downloaded filenames use metadata, not the Drive filename:

```text
科目名(教師名)年度_テスト種別_取得元.拡張子
```

Examples:

- `材料力学2(西川・林)2018後期_定期テスト_KU1025.pdf`
- `微分積分学A(山田)2020前期_小テスト2_KUwiki.pdf`

`sourceSite` value `京大wiki` becomes filename label `KUwiki`.

## Import Rules

- Valid `group` values are `人社群`, `自然群`, `外国語群`, `情報群`, `健康群`, `キャリア形成科目群`, `統合科学科目群`, `少人数教育科目群`, and `工学部専門科目`.
- KU1025 items under engineering specialty pages should use `工学部専門科目`, not `自然群` or `情報群`.
- Do not infer 前期/後期 from subject suffix `1`, `2`, `１`, or `２`.
- `A`/`B` and `Ⅰ`/`Ⅱ` may still be used for term inference.
- If KU1025 metadata cannot be determined, put it in `data/ku1025_unresolved.json`.
- `sourceSite` is shown in the UI but is not a text-search target.

## Generated Files

Do not include these in intentional diffs:

- `__pycache__/`
- `*.pyc`
- `kakomon_app.log`
- `.DS_Store`

## Verification

Minimum syntax check:

```sh
python3 -B -c 'import ast, pathlib; ast.parse(pathlib.Path("desktop_app.py").read_text()); ast.parse(pathlib.Path("drive_downloader.py").read_text()); ast.parse(pathlib.Path("scripts/import_kuwiki.py").read_text()); ast.parse(pathlib.Path("scripts/import_ku1025.py").read_text()); ast.parse(pathlib.Path("過去問検索.app/Contents/Resources/desktop_app.py").read_text()); ast.parse(pathlib.Path("過去問検索.app/Contents/Resources/drive_downloader.py").read_text())'
```
