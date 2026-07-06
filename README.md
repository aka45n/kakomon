# 過去問検索アプリ

京大系の過去問ファイルを、年度・教師名・科目名・群・テスト種別などの属性で検索するデスクトップアプリです。

元ファイルは主にGoogle Drive上にあります。アプリは完全オフラインでも起動・検索・ローカルファイル閲覧ができ、ローカルにファイルがない場合だけDrive参照やDriveからの保存を行います。

## 現在の方針

- ブラウザアプリではなく、Python `tkinter`によるデスクトップアプリとして作る
- データ本体は`data/exams.json`で管理する
- ダウンロード済みファイルは`files/`に置く
- `localFile`があればローカルファイルを優先して開く
- `localFile`がなくても`driveUrl`があればDrive参照・Driveからローカル保存ができる
- Drive URLの文字列は画面に直接表示しない
- `sourceSite`は画面に表示するが、キーワード検索対象には含めない
- サンプルデータは増やさない。現在の`data/exams.json`は空配列から開始する

## ファイル構成

```text
.
├── README.md
├── desktop_app.py
├── drive_downloader.py
├── data/
│   └── exams.json
└── files/
    └── .gitkeep
```

- `desktop_app.py`: アプリ本体。検索UI、絞り込み、一覧表示、ファイルを開く操作を担当
- `drive_downloader.py`: Google Driveからファイルを取得し、`files/`へ保存する処理を担当
- `data/exams.json`: 過去問メタデータの保存先
- `files/`: Driveから保存したファイルや手動配置したローカルファイルの保存先

## 起動方法

Python標準ライブラリだけで動く構成です。

```sh
python3 desktop_app.py
```

macOSでは`tkinter`がPythonに含まれていればそのまま起動できます。起動後、一覧で過去問を選択して操作します。

## 基本操作

- 左側の入力欄・プルダウンで絞り込み
- キーワードで年度、教師名、科目名、群、テスト種別、ローカルファイル名、注釈を検索
- テスト種別は`小テスト`と`定期テスト`のチェックボックスで絞り込み
- 一覧の過去問をダブルクリック、または`開く`ボタンで参照
- `ローカルファイルを開く`は`localFile`がある場合だけ使う
- `Driveを参照`は`driveUrl`がある場合だけ使う
- `Driveからローカル保存`はDriveから`files/`へ保存し、`data/exams.json`の`localFile`を更新する

## データ仕様

過去問は`data/exams.json`に配列で登録します。

```json
[
  {
    "id": "2025-math-yamada-a-regular",
    "year": "2025",
    "teacher": "山田先生",
    "subject": "数学I",
    "group": "A群",
    "testType": "定期テスト",
    "sourceSite": "京大wiki",
    "localFile": "./files/example.pdf",
    "driveUrl": "https://drive.google.com/...",
    "notes": "出題範囲: 三角比"
  }
]
```

各フィールドの意味:

- `id`: 一意なID。重複不可。英数字とハイフン推奨
- `year`: 年度。例: `2025`
- `teacher`: 教師名。例: `山田先生`
- `subject`: 科目名。例: `数学I`
- `group`: 群。例: `A群`
- `testType`: `小テスト`または`定期テスト`
- `sourceSite`: 取得元サイト。例: `京大wiki`, `KU1025`
- `localFile`: ローカルファイルパス。未保存なら空文字
- `driveUrl`: Google Driveリンク。未登録なら空文字
- `notes`: 注釈。なければ空文字

## 検索対象

キーワード検索に含めるもの:

- `year`
- `teacher`
- `subject`
- `group`
- `testType`
- `localFile`
- `notes`

キーワード検索に含めないもの:

- `sourceSite`
- `driveUrl`

`sourceSite`は一覧と選択詳細に表示しますが、検索対象にはしません。`driveUrl`も画面に直接表示せず、Drive操作ボタンの内部データとして使います。

## オフライン時の挙動

- アプリ起動、検索、絞り込み、一覧表示はオフラインで動作する
- `localFile`が存在する過去問はオフラインで開ける
- `localFile`がない過去問でも一覧には表示される
- `driveUrl`がある過去問は、オンライン時にDrive参照またはDriveからローカル保存ができる
- オフライン時にDrive操作を行うと失敗する可能性があるが、ローカルデータは消さない

## Drive保存の挙動

`Driveからローカル保存`を押すと、`drive_downloader.py`が以下を行います。

1. `data/exams.json`から対象レコードを探す
2. `driveUrl`をダウンロード用URLへ変換する
3. Google Driveからファイルを取得する
4. `files/`に保存する
5. 対象レコードの`localFile`を`./files/...`に更新する

Drive側の共有設定が不十分な場合や認証が必要なリンクでは保存できないことがあります。その場合でも`Driveを参照`でブラウザから確認できます。

## 実装上の注意

- ブラウザ版のファイルは不要。UIは`desktop_app.py`を中心にする
- サンプルデータは安易に追加しない
- 取得元サイトの属性名は`sourceSite`を使う
- Drive URLをUI上に直書き表示しない
- `sourceSite`を検索対象に入れない
- 新しいテスト種別を増やす場合は`desktop_app.py`の`TEST_TYPES`も更新する
- ローカルファイルを手動配置する場合は、原則`files/`配下に置いて`localFile`に`./files/ファイル名`を登録する

## 動作確認

構文チェック:

```sh
python3 -B -c 'import ast, pathlib; ast.parse(pathlib.Path("desktop_app.py").read_text())'
python3 -B -c 'import ast, pathlib; ast.parse(pathlib.Path("drive_downloader.py").read_text())'
```

起動確認:

```sh
python3 desktop_app.py
```

## 次にやること

- ユーザーからGoogle Driveリンクとメタデータを受け取る
- `data/exams.json`へ本データを追加する
- 必要に応じてDriveからローカル保存を試す
- データ量が増えたら、JSON編集支援やインポート機能を検討する
