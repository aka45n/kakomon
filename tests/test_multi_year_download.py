import io
import json
import tempfile
import unittest
from pathlib import Path

import drive_downloader
from desktop_app import KakomonApp, display_year, is_multi_year_source, parse_page_spec


class MultiYearDownloadTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        (self.root / "data").mkdir()
        self.originals = {
            "ROOT": drive_downloader.ROOT,
            "DATA_PATH": drive_downloader.DATA_PATH,
            "FILES_DIR": drive_downloader.FILES_DIR,
            "DRIVE_FILES_DIR": drive_downloader.DRIVE_FILES_DIR,
            "SEED_ROOT": drive_downloader.SEED_ROOT,
            "download_drive_content": drive_downloader.download_drive_content,
        }
        drive_downloader.ROOT = self.root
        drive_downloader.DATA_PATH = self.root / "data" / "exams.json"
        drive_downloader.FILES_DIR = self.root / "files"
        drive_downloader.DRIVE_FILES_DIR = self.root / "files" / "drive"
        drive_downloader.SEED_ROOT = None
        self.source = {
            "id": "range-source",
            "year": "2015-2016後期",
            "alternateYears": ["2015後期", "2016後期"],
            "teacher": "山下",
            "subject": "最適化入門",
            "group": "工学部専門科目",
            "testType": "定期テスト",
            "sourceSite": "KUInfo2020",
            "localFile": "未保存",
            "driveUrl": "https://example.test/source.pdf",
            "notes": "元資料",
        }
        drive_downloader.DATA_PATH.write_text(
            json.dumps([self.source], ensure_ascii=False),
            encoding="utf-8",
        )
        drive_downloader.download_drive_content = lambda _url: (self.pdf_bytes(3), "source.pdf")

    def tearDown(self):
        for name, value in self.originals.items():
            setattr(drive_downloader, name, value)
        self.tempdir.cleanup()

    def pdf_bytes(self, page_count):
        _, PdfWriter = drive_downloader.import_pypdf()
        writer = PdfWriter()
        for _ in range(page_count):
            writer.add_blank_page(width=100, height=100)
        output = io.BytesIO()
        writer.write(output)
        return output.getvalue()

    def test_page_specs_accept_ranges(self):
        self.assertEqual(parse_page_spec("1-3, 5"), [1, 2, 3, 5])
        with self.assertRaises(ValueError):
            parse_page_spec("3-1")

    def test_only_individual_years_appear_in_rotation(self):
        self.assertTrue(is_multi_year_source(self.source))
        self.assertEqual(display_year(self.source, 0), "2015後期")
        self.assertEqual(display_year(self.source, 1), "2016後期")
        self.assertEqual(display_year(self.source, 2), "2015後期")

    def test_range_source_is_excluded_from_bulk_download(self):
        app = object.__new__(KakomonApp)
        app.filtered = [self.source]
        self.assertEqual(KakomonApp.bulk_download_candidates(app), [])

    def test_download_creates_one_record_and_pdf_per_year(self):
        result = drive_downloader.download_exam_file(
            self.source["id"],
            {"2015後期": [1, 2], "2016後期": [3]},
        )

        exams = json.loads(drive_downloader.DATA_PATH.read_text(encoding="utf-8"))
        generated = [exam for exam in exams if exam.get("derivedFromExamId") == self.source["id"]]
        self.assertEqual(len(generated), 2)
        self.assertEqual({exam["year"] for exam in generated}, {"2015後期", "2016後期"})
        self.assertEqual(len(result["localFiles"]), 2)
        PdfReader, _ = drive_downloader.import_pypdf()
        page_counts = {
            exam["year"]: len(PdfReader(str(self.root / exam["localFile"])).pages)
            for exam in generated
        }
        self.assertEqual(page_counts, {"2015後期": 2, "2016後期": 1})
        self.assertTrue(all("driveUrl" not in exam for exam in generated))

        with self.assertRaisesRegex(ValueError, "すでに保存済み"):
            drive_downloader.download_exam_file(self.source["id"], {"2015後期": [1]})

    def test_range_record_is_hidden_only_after_every_year_exists(self):
        app = object.__new__(KakomonApp)
        files = []
        generated = []
        for year in self.source["alternateYears"]:
            path = self.root / f"{year}.pdf"
            path.write_bytes(b"saved")
            files.append(path)
            generated.append({
                "id": f"generated-{year}",
                "year": year,
                "derivedFromExamId": self.source["id"],
                "localFile": str(path),
            })
        app.exams = [self.source, *generated]

        self.assertFalse(KakomonApp.should_show_exam(app, self.source))
        files[0].unlink()
        self.assertTrue(KakomonApp.should_show_exam(app, self.source))


if __name__ == "__main__":
    unittest.main()
