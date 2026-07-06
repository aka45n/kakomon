# 過去問検索アプリ

年度、教師名、科目名、群、テスト種別、ローカルファイルまたはGoogle Driveリンク、注釈を紐付けて検索するデスクトップアプリです。

## 使い方

デスクトップアプリとして起動します。

```sh
python3 desktop_app.py
```

一覧で過去問を選択し、ローカルに保存済みならローカルファイルを開きます。ローカルにない場合はDriveを参照できます。

## データ追加

過去問は`data/exams.json`に追加します。

```json
{
  "id": "2025-math-yamada-a-regular",
  "year": "2025",
  "teacher": "山田先生",
  "subject": "数学I",
  "group": "A群",
  "testType": "定期テスト",
  "localFile": "./files/example.pdf",
  "driveUrl": "https://drive.google.com/...",
  "notes": "出題範囲: 三角比"
}
```

`localFile`と`driveUrl`はどちらか一方だけでも登録できます。`localFile`が空で`driveUrl`がある場合、検索結果ではDrive参照を優先して表示し、Driveからローカルへ保存できます。

Driveから保存したファイルは`files/`に配置され、`data/exams.json`の`localFile`も自動更新されます。
