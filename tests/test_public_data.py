import unittest
from datetime import date
from io import BytesIO
from unittest.mock import patch
from urllib.error import URLError

from almanac import _cash_metrics, build_dashboard
from public_data import _fetch, _xlsx_gold_silver, parse_bls_work_stoppages, parse_census_timeseries, parse_eia_canada_oil, parse_eia_gasoline, parse_eia_residential_gas, parse_eia_monthly_price, parse_conflict_rss, parse_sec_form4_atom, parse_treasury
from storage import all_series, init_db, save_error, save_source, save_news, recent_news, source_status
import tempfile
from pathlib import Path


class PublicDataParserTests(unittest.TestCase):
    def test_fetch_retries_transient_network_failure(self):
        class Response(BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.close()

        with patch("public_data.urlopen", side_effect=[URLError("packet loss"), Response(b"ok")]) as fetch, patch("public_data.time.sleep") as sleep:
            self.assertEqual(_fetch("https://example.test/data"), "ok")
        self.assertEqual(fetch.call_count, 2)
        sleep.assert_called_once_with(0.5)

    def test_treasury_bill_table(self):
        html = """<table><tr><th>Date</th><th>4 Weeks Bank Discount</th><th>Coupon Equivalent</th><th>13 Weeks Bank Discount</th><th>Coupon Equivalent</th><th>26 Weeks Bank Discount</th><th>Coupon Equivalent</th><th>52 Weeks Bank Discount</th><th>Coupon Equivalent</th></tr><tr><td>01/02/2025</td><td>4.10</td><td>4.20</td><td>4.00</td><td>4.10</td><td>3.90</td><td>4.00</td><td>3.70</td><td>3.80</td></tr></table>"""
        rows = parse_treasury(html, "bill", 2025)
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[1]["series_key"], "treasury_13w_yield")
        self.assertEqual(rows[1]["value"], 4.1)

    def test_census_seasonal_factors(self):
        text = """MONTHLY SALES\n2024 100 101 102 103 104 105 106 107 108 109 110 111\nSEASONAL FACTORS\n2024 0.91 0.92 0.93 0.94 0.95 0.96 0.97 0.98 0.99 1.00 1.01 1.02\n"""
        rows = parse_census_timeseries(text, "census_sample")
        self.assertEqual(len(rows), 24)
        self.assertEqual(rows[12]["series_key"], "census_sample_factor")
        self.assertEqual(rows[-1]["period"], "2024-12")
        self.assertEqual(rows[-1]["value"], 1.02)

    def test_eia_monthly_residential_gas(self):
        cells = "".join(f"<td>{value}</td>" for value in ["2024", *range(1, 13)])
        rows = parse_eia_residential_gas(f"<table><tr>{cells}</tr></table>")
        self.assertEqual(len(rows), 12)
        self.assertEqual(rows[0]["period"], "2024-01")
        self.assertEqual(rows[-1]["value"], 12)

    def test_eia_gasoline_drops_future_observation(self):
        html = "<table><tr><td>2025-Jan</td><td>01/01</td><td>9000</td><td>01/08</td><td>9100</td></tr></table>"
        rows = parse_eia_gasoline(html, date(2025, 1, 3))
        self.assertEqual([row["period"] for row in rows], ["2025-01-01"])

    def test_eia_canada_monthly_trade(self):
        cells = "".join(f"<td>{value}</td>" for value in ["2025", *range(1, 13)])
        rows = parse_eia_canada_oil(f"<table><tr>{cells}</tr></table>")
        self.assertEqual(len(rows), 12)
        self.assertEqual(rows[0]["series_key"], "eia_canada_net_imports")
        self.assertEqual(rows[-1]["period"], "2025-12")

    def test_bls_work_stoppages(self):
        html = "<table><tr><td>2025</td><td>30</td><td>32</td><td>306.8</td><td>374.3</td><td>1991.2</td><td>0.01</td></tr></table>"
        rows = parse_bls_work_stoppages(html)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["value"], 30)
        self.assertEqual(rows[1]["value"], 306.8)

    def test_bls_factsheet_two_column_fallback(self):
        html = "<table><tr><th>Year</th><th>Number of work stoppages beginning</th></tr><tr><td>2024</td><td>31</td></tr><tr><td>2025</td><td>30</td></tr></table>"
        rows = parse_bls_work_stoppages(html)
        self.assertEqual(rows, [
            {"series_key": "bls_stoppages", "period": "2024", "value": 31.0, "unit": "stoppages"},
            {"series_key": "bls_stoppages", "period": "2025", "value": 30.0, "unit": "stoppages"},
        ])

    def test_eia_monthly_benchmark_parser(self):
        cells = "".join(f"<td>{value}</td>" for value in ["2025", *range(1, 13)])
        rows = parse_eia_monthly_price(f"<table><tr>{cells}</tr></table>", "eia_wti")
        self.assertEqual((rows[0]["period"], rows[-1]["value"]), ("2025-01", 12.0))

    def test_conflict_rss_is_current_keyword_filtered_and_stored(self):
        xml = """<rss><channel><item><title>Ceasefire talks resume</title><link>https://news.example/a</link><description>Diplomats discuss a ceasefire.</description><pubDate>Fri, 25 Sep 2026 10:00:00 GMT</pubDate></item><item><title>New album released</title><link>https://news.example/b</link><description>Music news</description></item></channel></rss>"""
        from public_data import parse_conflict_rss
        stories = parse_conflict_rss(xml)
        self.assertEqual(len(stories), 1)
        with tempfile.TemporaryDirectory() as folder:
            db_path = str(Path(folder) / "cache.sqlite")
            init_db(db_path)
            metadata = {"title": "Feed", "url": "https://news.example/rss"}
            save_news("bbc", metadata, stories, "2026-09-25T10:00:00+00:00", db_path)
            self.assertEqual(recent_news("bbc", db_path=db_path)[0]["title"], "Ceasefire talks resume")

    def test_sec_form4_atom_parser_keeps_official_filing_link(self):
        atom = '''<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>4 - EXAMPLE CORP (Issuer) (Filer)</title><link rel="alternate" href="https://www.sec.gov/Archives/edgar/data/1/000000000026000001/"/><updated>2026-09-25T14:00:00Z</updated><summary>Statement of changes in beneficial ownership</summary></entry></feed>'''
        entries = parse_sec_form4_atom(atom)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["title"], "4 - EXAMPLE CORP (Issuer) (Filer)")
        self.assertTrue(entries[0]["url"].startswith("https://www.sec.gov/Archives/"))

    def test_world_bank_xlsx_gold_silver_parser(self):
        from zipfile import ZipFile
        workbook = BytesIO()
        with ZipFile(workbook, "w") as archive:
            archive.writestr("xl/workbook.xml", '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Monthly Prices" sheetId="1" r:id="rId1"/></sheets></workbook>')
            archive.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
            archive.writestr("xl/sharedStrings.xml", '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><si><t>Month</t></si><si><t>Gold</t></si><si><t>Silver</t></si><si><t>2025M01</t></si></sst>')
            archive.writestr("xl/worksheets/sheet1.xml", '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c><c r="C1" t="s"><v>2</v></c></row><row r="2"><c r="A2" t="s"><v>3</v></c><c r="B2"><v>2700.5</v></c><c r="C2"><v>30.2</v></c></row></sheetData></worksheet>')
        rows = _xlsx_gold_silver(workbook.getvalue())
        self.assertEqual([(row["series_key"], row["value"]) for row in rows], [("worldbank_gold", 2700.5), ("worldbank_silver", 30.2)])


class CacheAndCalendarTests(unittest.TestCase):
    def test_cash_card_falls_back_to_available_treasury_curve(self):
        result = _cash_metrics({"treasury_3m_par": [{"period": "2026-09-24", "value": 4.24}]})
        self.assertEqual(result["headline"], "4.24%")
        self.assertIn("proxy", result["caption"])

    def test_cache_upserts_and_retains_good_data_after_error(self):
        with tempfile.TemporaryDirectory() as folder:
            db_path = str(Path(folder) / "cache.sqlite")
            init_db(db_path)
            metadata = {"title": "Sample", "url": "https://example.test/data"}
            save_source("sample", metadata, [{"series_key": "s", "period": "2024-01", "value": 1.5, "unit": "u"}], "2025-01-01T00:00:00+00:00", db_path)
            save_error("sample", metadata, "temporary network error", "2025-01-02T00:00:00+00:00", db_path)
            self.assertEqual(all_series(db_path)["s"][0]["value"], 1.5)
            self.assertEqual(source_status(db_path)[0]["last_error"], "temporary network error")

    def test_heating_season_spans_calendar_year(self):
        dashboard = build_dashboard({}, [], {}, date(2026, 2, 15))
        self.assertIn("winter_heating", [card["id"] for card in dashboard["cards"] if card["state"] == "in season"])
        self.assertIn("winter_heating", [item["id"] for item in dashboard["calendar"][2]])

    def test_dynamic_conflict_and_industry_cards_show_all_year(self):
        dashboard = build_dashboard({}, [], {}, date(2026, 9, 25))
        self.assertIn("work_stoppages", dashboard["featured_ids"])
        self.assertIn("canada_energy", dashboard["featured_ids"])
        self.assertIn("conflict_watch", dashboard["featured_ids"])
        self.assertIn("energy_industry", dashboard["featured_ids"])
        self.assertIn("precious_metals", dashboard["featured_ids"])
        self.assertNotIn("old_timer_wisdom", [card["id"] for card in dashboard["cards"]])
        cards_by_id = {card["id"]: card for card in dashboard["cards"]}
        self.assertEqual(cards_by_id["rates"]["wisdom_note"]["tradition"], "Chinese proverb · English translation; wording varies")
        self.assertIn("Islamic hadith", cards_by_id["cash"]["wisdom_note"]["tradition"])
        self.assertIn("Dàodéjīng", cards_by_id["back_to_school"]["wisdom_note"]["tradition"])
        self.assertIn("Shakespeare", cards_by_id["precious_metals"]["wisdom_note"]["tradition"])
        filings = cards_by_id["public_trade_filings"]
        self.assertEqual(len(filings["reference_links"]), 4)
        self.assertIn("Senate", filings["metrics"]["headline"])
        disclosure = [{"title": "Form 4 · sample filer", "url": "https://www.sec.gov/Archives/edgar/data/1/", "published": "today"}]
        with_filings = build_dashboard({}, [], {}, date(2026, 9, 25), disclosure_stories=disclosure)
        public_card = next(card for card in with_filings["cards"] if card["id"] == "public_trade_filings")
        self.assertEqual(public_card["stories"], disclosure)
        self.assertEqual(public_card["metrics"]["headline"], "1 recent Form 4 filings")
        metals = build_dashboard({"worldbank_gold": [
            {"period": "2025-01", "value": 100.0, "unit": "USD/troy ounce"},
            {"period": "2026-01", "value": 130.0, "unit": "USD/troy ounce"},
        ]}, [], {}, date(2026, 2, 1))
        gold = next(card for card in metals["cards"] if card["id"] == "precious_metals")
        self.assertEqual(gold["opportunity"]["label"], "BUY-SIDE MOMENTUM WATCH")
        self.assertIn("30.0% up", gold["opportunity"]["detail"])
        self.assertIn("not whether gold is cheap or overvalued", gold["opportunity"]["detail"])
        cash = build_dashboard({"treasury_13w_yield": [
            {"period": "2026-09-24", "value": 4.1, "unit": "percent annualized"},
        ]}, [], {}, date(2026, 9, 25))
        cash_card = next(card for card in cash["cards"] if card["id"] == "cash")
        self.assertEqual(cash_card["opportunity"]["label"], "BUY-SIDE INCOME IDEA: short-term T-bills")
        self.assertIn("4.10% annualized", cash_card["opportunity"]["detail"])
        retail = build_dashboard({
            "census_general_factor": [
                {"period": "2025-11", "value": 1.1},
                {"period": "2025-12", "value": 1.1},
            ],
        }, [], {}, date(2026, 11, 1))
        holiday = next(card for card in retail["cards"] if card["id"] == "holiday_shopping")
        self.assertIn("BUY-SIDE SEASONAL TAILWIND", holiday["opportunity"]["label"])
        stories = [{"title": "Fresh ceasefire report", "url": "https://news.example/a", "published": "today"}]
        updated = build_dashboard({}, [], {}, date(2026, 2, 1), news_stories=stories)
        conflict = next(card for card in updated["cards"] if card["id"] == "conflict_watch")
        self.assertEqual(conflict["stories"], stories)
        self.assertIn("current headlines", conflict["metrics"]["headline"])


if __name__ == "__main__":
    unittest.main()
