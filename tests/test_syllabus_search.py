import unittest

from syllabus_search import SyllabusSearchEngine, normalize_search_text, record_year


class SyllabusSearchTests(unittest.TestCase):
    def setUp(self):
        self.records = [
            {"授業科目名": "微分積分学Ａ", "前身科目": "", "担当者名": "山田 太郎", "群": "自然群", "年度": "2026"},
            {"授業科目名": "計算機アーキテクチャ", "前身科目": "", "担当者名": "岡部 寿男", "群": "工学部専門科目", "年度": "2025"},
            {"授業科目名": "情報学概論", "前身科目": "数理工学概論", "担当者名": "佐藤 花子", "群": "工学部専門科目"},
        ]
        self.engine = SyllabusSearchEngine(self.records)

    def test_calculus_aliases_are_equivalent(self):
        canonical = normalize_search_text("微分積分学")
        self.assertEqual(normalize_search_text("微積"), normalize_search_text("微分積分"))
        self.assertEqual(normalize_search_text("微積分学"), canonical)
        for query in ("微積", "微積分学", "微分積分"):
            self.assertEqual(self.engine.search(query)[0]["授業科目名"], "微分積分学Ａ")

    def test_partial_title_produces_suggestion(self):
        self.assertEqual(self.engine.suggestions("アーキ"), ["計算機アーキテクチャ"])

    def test_predecessor_title_is_searchable(self):
        self.assertEqual(self.engine.search("数理工学概論")[0]["授業科目名"], "情報学概論")

    def test_empty_query_has_no_results(self):
        self.assertEqual(self.engine.search(""), [])

    def test_year_filter_and_default_year(self):
        self.assertEqual(self.engine.years, ["2026", "2025"])
        self.assertEqual(self.engine.search("微分積分", year="2025"), [])
        self.assertEqual(self.engine.search("アーキ", year="2025")[0]["授業科目名"], "計算機アーキテクチャ")
        self.assertEqual(record_year(self.records[2]), "2026")


if __name__ == "__main__":
    unittest.main()
