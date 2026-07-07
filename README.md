# 過去問検索アプリ

京大系の過去問ファイルを、科目名・教師名・年度・科目群・テスト種別などの属性で検索するデスクトップアプリです。

元ファイルは主にGoogle Drive上にあります。アプリは完全オフラインでも起動・検索・ローカルファイル閲覧ができ、ローカルにファイルがない場合だけDrive参照やDriveからの保存を行います。

## 現在の方針

- ブラウザアプリではなく、Python `tkinter`によるデスクトップアプリとして作る
- データ本体は`data/exams.json`で管理する
- 過去問ごとの修正メモは`data/feedback.json`で管理する
- ダウンロード済みファイルは`files/`に置く
- `localFile`があればローカルファイルを優先して開く
- `localFile`がなくても`driveUrl`があればDrive参照・Driveからローカル保存ができる
- Drive URLの文字列は画面に直接表示しない
- `sourceSite`は画面に表示するが、キーワード検索対象には含めない
- 科目群は指定の8種類から選択する。既存データの未対応タグは一旦スキップし、自動変換しない
- 過去問の情報欠けや修正したい点は、選択中の過去問にメモとして残せる
- 京大wikiから取得した京都大学の過去問メタデータを`data/exams.json`に登録する
- 京大wikiの命名規則に合わないファイルや空フォルダは`data/kuwiki_unresolved.json`に残す

## ファイル構成

```text
.
├── README.md
├── desktop_app.py
├── drive_downloader.py
├── data/
│   ├── exams.json
│   ├── feedback.json
│   └── kuwiki_unresolved.json
├── scripts/
│   └── import_kuwiki.py
└── files/
    └── .gitkeep
```

- `desktop_app.py`: アプリ本体。検索UI、絞り込み、一覧表示、ファイルを開く操作を担当
- `drive_downloader.py`: Google Driveからファイルを取得し、`files/`へ保存する処理を担当
- `data/exams.json`: 過去問メタデータの保存先
- `data/feedback.json`: Codexに後で直してもらうための過去問別メモ
- `data/kuwiki_unresolved.json`: 京大wikiから取得したが、命名規則上メタデータを確定できなかった項目
- `scripts/import_kuwiki.py`: 京大wiki検索APIと公開Driveフォルダからメタデータを取り込む補助スクリプト
- `files/`: Driveから保存したファイルや手動配置したローカルファイルの保存先

## 起動方法

Python標準ライブラリだけで動く構成です。

macOSでは、Finderから次をダブルクリックして起動できます。

```text
過去問検索.app
```

ターミナルから起動する場合:

```sh
python3 desktop_app.py
```

`過去問検索.app`は`Contents/Resources`内のPythonコードを起動します。初回起動時に同梱データを`~/Library/Application Support/Kakomon/`へコピーし、その後のメモ、ダウンロード済みファイル、更新された`exams.json`はそこへ保存します。`tkinter`がPythonに含まれていればそのまま起動できます。起動後、一覧で過去問を選択して操作します。

## 基本操作

- 初回は中央の検索フォームに条件を入力して`検索`を押す
- 初回の中央画面はホーム画面として扱う
- ホーム画面右上の`過去問を追加`から、ファイルと主要情報を入力して過去問を追加できる
- 検索後は左側に検索条件が表示され、2回目以降は条件変更が即時に結果へ反映される
- 検索後は`ホームへ`ボタンでホーム画面に戻れる
- 科目名と教師名は入力検索
- 年度、科目群、テスト種別は選択式
- 起動直後は検索結果を表示しない
- 初回の科目名・教師名の入力欄ではReturnキーでも検索できる
- 検索条件は最低1つだけでも使え、複数条件を組み合わせても検索できる
- 条件なしで検索した場合は結果を表示しない
- 検索後の`条件をクリア`で中央検索画面に戻る
- テスト種別は`小テスト`または`定期テスト`から選択する
- 一覧の過去問をダブルクリックすると、ローカルファイルがあればローカルを開き、なければDriveを開く
- 詳細画面は下部の`詳細を表示`ボタン、または検索結果の右クリックメニューから開く
- 右クリックメニューから`ファイルの場所を開く`も実行できる
- 検索結果一覧にはファイル情報や注釈を表示しない。ファイル操作や詳しい情報は詳細画面で行う
- `開く`はローカルファイルが存在すればローカルを開き、なければDriveを開く
- `ファイルの場所を開く`はローカルファイルが存在すれば保存場所を開き、なければDriveを開く
- `Driveからローカル保存`はDriveから保存先の`files/`へ保存し、`data/exams.json`の`localFile`を更新する
- すでにローカルファイルが存在する過去問では、Driveからの再ダウンロードは行わない
- 情報が欠けている過去問や後で直したい過去問には、詳細画面のメモ欄からコメントを保存する

## 過去問の手動追加

ホーム画面右上の`過去問を追加`から、手元のファイルまたはDrive URLを登録できます。

入力できる主な情報:

- ファイル
- 年度
- 教師名
- 科目名
- 科目群
- テスト種別
- 取得元
- Drive URL
- 注釈

年度、科目名、科目群、テスト種別は必須です。ファイルまたはDrive URLのどちらかも必須です。ファイルを選んだ場合は保存先の`files/`へコピーされ、`localFile`に自動登録されます。

## データ仕様

過去問は`data/exams.json`に配列で登録します。

Finderから`過去問検索.app`を使う場合の実データ保存先:

```text
~/Library/Application Support/Kakomon/data/exams.json
~/Library/Application Support/Kakomon/data/feedback.json
~/Library/Application Support/Kakomon/files/
```

```json
[
  {
    "id": "2025-math-yamada-a-regular",
    "year": "2025",
    "teacher": "山田",
    "subject": "数学I",
    "group": "自然群",
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
- `year`: 年度。例: `2025`, `2025前期`, `2025後期`
- `teacher`: 教師名。例: `山田`
- `subject`: 科目名。例: `数学I`
- `group`: 科目群。下記の8種類のいずれか
- `testType`: `小テスト`または`定期テスト`。`過去問`という種別は使わない
- `sourceSite`: 取得元サイト。例: `京大wiki`, `KU1025`
- `localFile`: ローカルファイルパス。未保存なら空文字
- `driveUrl`: Google Driveリンク。未登録なら空文字
- `notes`: 注釈。なければ空文字

## 科目群

科目群は次のどれかにしてください。

- `人社群`
- `自然群`
- `外国語群`
- `情報群`
- `健康群`
- `キャリア形成科目群`
- `統合科学科目群`
- `少人数教育科目群`

現在登録済みのデータには、京大wiki由来の`全学：人社`や`理：物理`など、この分類に対応していないタグが含まれている可能性があります。現時点ではそれらを自動変換せず、必要になった時点で手動または変換スクリプトで対応します。

## 検索対象

検索条件として使うもの:

- `subject`
- `teacher`
- `year`
- `group`
- `testType`

検索条件として使わないもの:

- `sourceSite`
- `driveUrl`
- `localFile`
- `notes`

科目名と教師名は入力された文字列を部分一致で検索します。年度、科目群、テスト種別は選択式で完全一致します。

`sourceSite`は一覧と選択詳細に表示しますが、検索対象にはしません。`driveUrl`も画面に直接表示せず、Drive操作ボタンの内部データとして使います。

## フィードバックメモ

過去問一覧で対象を選択し、`Codexに直してもらうメモ`へコメントを書くと`data/feedback.json`へ保存されます。

用途:

- 教師名が欠けている
- 年度が怪しい
- 科目群の変換が必要
- 注釈を後で整理したい
- Driveリンクやローカルファイルの対応を後で確認したい

保存形式:

```json
[
  {
    "id": "feedback-2026-07-07T12:34:56-kuwiki-example",
    "examId": "kuwiki-example",
    "createdAt": "2026-07-07T12:34:56",
    "status": "open",
    "comment": "教師名が空欄。Driveファイル名を確認する。",
    "snapshot": {
      "year": "2025",
      "subject": "数学I",
      "teacher": "",
      "group": "自然群",
      "testType": "定期テスト",
      "sourceSite": "京大wiki"
    }
  }
]
```

`status`は現時点では`open`のみをアプリで表示対象にしています。Codexが後で修正したら、必要に応じて`resolved`などへ変更できます。

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

Drive側の共有設定が不十分な場合や認証が必要なリンクでは保存できないことがあります。その場合でも、ローカルファイルがない状態で`開く`または`ファイルの場所を開く`を押すとDriveをブラウザで確認できます。

## 実装上の注意

- ブラウザ版のファイルは不要。UIは`desktop_app.py`を中心にする
- 取得元サイトの属性名は`sourceSite`を使う
- Drive URLをUI上に直書き表示しない
- `sourceSite`を検索対象に入れない
- 科目群を変更する場合は`desktop_app.py`の`COURSE_GROUPS`とREADMEを両方更新する
- 新しいテスト種別を増やす場合は`desktop_app.py`の`TEST_TYPES`も更新する
- ローカルファイルを手動配置する場合は、原則`files/`配下に置いて`localFile`に`./files/ファイル名`を登録する

## 京大wiki取り込み

京大wikiの検索APIで科目フォルダを集め、各Google Drive公開フォルダ内のファイル名からメタデータを作ります。

```sh
python3 scripts/import_kuwiki.py
```

取り込み対象にする命名規則:

```text
科目名(教官名)西暦年度.拡張子
科目名(教官名)西暦年度前期.拡張子
科目名(教官名)西暦年度後期.拡張子
```

- 対応拡張子は`pdf`, `jpg`, `jpeg`, `png`, `gif`, `tif`, `tiff`, `txt`, `doc`, `docx`, `rtf`, `html`, `pptx`
- 年度は4桁の西暦、または西暦に`前期`/`後期`を付けた文字列として保存する
- `前期`と`後期`は年度値の一部として扱い、別の年度値として絞り込める
- 教官名が空欄の`科目名()2025.pdf`も登録し、注釈に空欄理由を残す
- 年度がない、年度の後ろに`解答`や`レポート`などが続く項目は`data/kuwiki_unresolved.json`へ保存する

## 動作確認

構文チェック:

```sh
python3 -B -c 'import ast, pathlib; ast.parse(pathlib.Path("desktop_app.py").read_text())'
python3 -B -c 'import ast, pathlib; ast.parse(pathlib.Path("drive_downloader.py").read_text())'
python3 -B -c 'import ast, pathlib; ast.parse(pathlib.Path("scripts/import_kuwiki.py").read_text())'
```

起動確認:

```sh
python3 desktop_app.py
```

## 次にやること

- `data/kuwiki_unresolved.json`のうち、ファイル名だけでは判別できない項目を確認する
- 必要に応じてDriveからローカル保存を試す
- データ量が増えたら、JSON編集支援やインポート機能を検討する
