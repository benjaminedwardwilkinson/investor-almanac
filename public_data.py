"""Small no-key adapters for official U.S. economic-data downloads."""

from __future__ import annotations

import re
import time
import io
import csv
import zipfile
import xml.etree.ElementTree as ET
from html import unescape
from datetime import date, datetime, timezone
from urllib.error import HTTPError, URLError
from html.parser import HTMLParser
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from config import FRED_API_KEY, REQUEST_TIMEOUT


TREASURY_TEXT = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView"
EIA_GAS = "https://www.eia.gov/dnav/ng/hist/n3010us2m.htm"
EIA_GASOLINE = "https://www.eia.gov/dnav/pet/hist/LeafHandler.ashx?f=W&n=PET&s=WGFUPUS2"
EIA_CANADA_OIL = "https://www.eia.gov/dnav/pet/hist/LeafHandler.ashx?f=M&n=PET&s=MTTNTUSCA2"
EIA_WTI = "https://www.eia.gov/dnav/pet/hist/rwtcm.htm"
EIA_WTI_DATA = "https://www.eia.gov/dnav/pet/hist/LeafHandler.ashx?n=PET&s=RWTC&f=M"
EIA_BRENT = "https://www.eia.gov/dnav/pet/hist/LeafHandler.ashx?f=M&n=PET&s=RBRTE"
EIA_HENRY_HUB = "https://www.eia.gov/dnav/ng/hist/rngwhhdm.htm"
EIA_RENEWABLES = "https://www.eia.gov/electricity/monthly/epm_table_grapher.php?t=table_1_01_a"
WORLD_BANK_COMMODITIES = "https://www.worldbank.org/en/research/commodity-markets"
BBC_WORLD_RSS = "https://feeds.bbci.co.uk/news/world/rss.xml"
SEC_FORM4_FEED = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=4&company=&dateb=&owner=only&count=40&output=atom"
BLS_WORK_STOPPAGES = "https://www.bls.gov/wsp/factsheets/summary-of-work-stoppages-in-the-united-states.htm"
BLS_WORK_STOPPAGES_FALLBACK = "https://www.bls.gov/wsp/"
BLS_API = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
CENSUS_BASE = "https://www.census.gov/retail/marts/www/"
FRED_OBSERVATIONS = "https://api.stlouisfed.org/fred/series/observations"
IRS_FILING_STATS = "https://www.irs.gov/pub/newsroom/filing-season-statistics-2009-to-current-year.csv"
FRED_INDEX_SERIES = {
    "fred_sp500": ("SP500", "S&P 500"),
    "fred_djia": ("DJIA", "Dow Jones Industrial Average"),
    "fred_nasdaq_composite": ("NASDAQCOM", "NASDAQ Composite"),
}

SOURCES = {
    "fred_sp500": {"title": "S&P 500 · daily index history", "url": "https://fred.stlouisfed.org/series/SP500"},
    "fred_djia": {"title": "Dow Jones Industrial Average · daily index history", "url": "https://fred.stlouisfed.org/series/DJIA"},
    "fred_nasdaq_composite": {"title": "NASDAQ Composite · daily index history", "url": "https://fred.stlouisfed.org/series/NASDAQCOM"},
    "treasury_bills": {
        "title": "U.S. Treasury daily bill rates",
        "url": TREASURY_TEXT + "?type=daily_treasury_bill_rates",
    },
    "treasury_curve": {
        "title": "U.S. Treasury par yield curve",
        "url": TREASURY_TEXT + "?type=daily_treasury_yield_curve",
    },
    "census_total": {"title": "Census retail and food services", "url": CENSUS_BASE + "adv44X72.txt"},
    "census_clothing": {"title": "Census clothing retail", "url": CENSUS_BASE + "adv44800.txt"},
    "census_electronics": {"title": "Census electronics retail", "url": CENSUS_BASE + "adv44300.txt"},
    "census_general": {"title": "Census general merchandise retail", "url": CENSUS_BASE + "adv45200.txt"},
    "census_nonstore": {"title": "Census nonstore retail", "url": CENSUS_BASE + "adv45400.txt"},
    "census_building": {"title": "Census building and garden retail", "url": CENSUS_BASE + "adv44400.txt"},
    "eia_residential_gas": {"title": "EIA residential natural-gas consumption", "url": EIA_GAS},
    "eia_gasoline": {"title": "EIA weekly gasoline product supplied", "url": EIA_GASOLINE},
    "eia_canada_oil": {"title": "EIA U.S.–Canada net petroleum imports", "url": EIA_CANADA_OIL},
    "bls_work_stoppages": {"title": "BLS major work stoppages · monthly series", "url": "https://www.bls.gov/wsp/data/"},
    "eia_wti": {"title": "EIA WTI crude-oil price", "url": EIA_WTI},
    "eia_brent": {"title": "EIA Brent crude-oil price", "url": EIA_BRENT},
    "eia_henry_hub": {"title": "EIA Henry Hub natural-gas price", "url": EIA_HENRY_HUB},
    "eia_renewable_power": {"title": "EIA monthly U.S. renewable electricity generation", "url": EIA_RENEWABLES},
    "worldbank_metals": {"title": "World Bank monthly gold and silver prices", "url": WORLD_BANK_COMMODITIES},
    "bbc_conflict_news": {"title": "BBC World conflict-related headlines", "url": BBC_WORLD_RSS},
    "sec_form4_feed": {"title": "SEC latest Form 4 ownership filings", "url": SEC_FORM4_FEED},
    "irs_filing_stats": {"title": "IRS weekly filing-season refund statistics", "url": IRS_FILING_STATS},
}


def parse_fred_observations(payload: dict, series_key: str) -> list[dict]:
    """Parse daily FRED index observations, omitting its dot-valued market holidays."""
    if payload.get("error_code"):
        raise ValueError(f"FRED API error {payload['error_code']}: {payload.get('error_message', 'request rejected')[:180]}")
    rows = []
    for observation in payload.get("observations", []):
        value = _float(str(observation.get("value", "")))
        period = str(observation.get("date", ""))
        if value is None or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", period):
            continue
        rows.append({"series_key": series_key, "period": period, "value": value, "unit": "index points"})
    if not rows:
        raise ValueError(f"FRED returned no daily observations for {series_key}")
    return rows


def parse_irs_filing_statistics(text: str) -> list[dict]:
    """Parse the IRS's public weekly filing-season CSV (2009 to current year)."""
    output = []
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 15 or not re.fullmatch(r"\d{4}", row[0].strip()):
            continue
        try:
            period = date(int(row[0]), int(row[1]), int(row[2])).isoformat()
        except (ValueError, TypeError):
            continue
        for index, key, unit in (
            (9, "irs_refund_count", "refunds"),
            (10, "irs_refund_amount", "billion USD"),
            (11, "irs_refund_average", "USD per refund"),
        ):
            value = _float(row[index].replace("$", ""))
            if value is not None:
                output.append({"series_key": key, "period": period, "value": value, "unit": unit})
    if not output:
        raise ValueError("IRS filing-season CSV contained no weekly refund observations")
    return output


def _ten_year_start(today: date) -> date:
    try:
        return today.replace(year=today.year - 10)
    except ValueError:  # February 29 ten years earlier
        return today.replace(year=today.year - 10, day=28)


def fetch_fred_index(source_key: str, today: date) -> list[dict]:
    if not FRED_API_KEY:
        raise ValueError("Set FRED_API_KEY in the Pi's .env file to download index history")
    series_id, _label = FRED_INDEX_SERIES[source_key]
    params = urlencode({
        "series_id": series_id,
        "api_key": FRED_API_KEY,
        "file_type": "json",
        "observation_start": _ten_year_start(today).isoformat(),
        "observation_end": today.isoformat(),
        "sort_order": "asc",
    })
    import json
    payload = json.loads(_fetch(f"{FRED_OBSERVATIONS}?{params}"))
    return parse_fred_observations(payload, source_key)


class _TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self.table: list[list[str]] | None = None
        self.row: list[str] | None = None
        self.cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.table = []
        elif tag == "tr" and self.table is not None:
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None and self.row is not None:
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.row is not None and self.table is not None:
            self.table.append(self.row)
            self.row = None
        elif tag == "table" and self.table is not None:
            self.tables.append(self.table)
            self.table = None


def _float(value: str) -> float | None:
    cleaned = value.strip().replace(",", "")
    if not cleaned or cleaned.upper() in {"N/A", "NA", "--", "-"}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _fetch(url: str) -> str:
    request = Request(url, headers={"User-Agent": "InvestorAlmanac/0.3 (self-hosted educational project)"})
    retryable_statuses = {408, 425, 429, 500, 502, 503, 504}
    for attempt in range(3):
        try:
            with urlopen(request, timeout=REQUEST_TIMEOUT) as response:
                return response.read().decode("utf-8-sig", errors="replace")
        except HTTPError as exc:
            if exc.code not in retryable_statuses or attempt == 2:
                raise
        except (URLError, TimeoutError, OSError):
            if attempt == 2:
                raise
        time.sleep(0.5 * (2 ** attempt))
    raise RuntimeError("Public data request failed after retries")


def _fetch_bytes(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "InvestorAlmanac/0.3 (self-hosted educational project)"})
    retryable_statuses = {408, 425, 429, 500, 502, 503, 504}
    for attempt in range(3):
        try:
            with urlopen(request, timeout=REQUEST_TIMEOUT) as response:
                return response.read()
        except HTTPError as exc:
            if exc.code not in retryable_statuses or attempt == 2:
                raise
        except (URLError, TimeoutError, OSError):
            if attempt == 2:
                raise
        time.sleep(0.5 * (2 ** attempt))
    raise RuntimeError("Public data request failed after retries")


def _rows_for_year(html: str, wanted_year: int) -> tuple[list[str], list[list[str]]]:
    parser = _TableParser()
    parser.feed(html)
    if not parser.tables:
        raise ValueError("Treasury page contained no data table")
    table = parser.tables[0]
    if not table:
        raise ValueError("Treasury data table was empty")
    headers = [re.sub(r"\s+", " ", value).strip().upper() for value in table[0]]
    rows = []
    for row in table[1:]:
        if not row:
            continue
        if re.match(rf"\d{{2}}/\d{{2}}/{wanted_year}$", row[0].strip()):
            rows.append(row)
    return headers, rows


def parse_treasury(html: str, table_type: str, year: int | None = None) -> list[dict]:
    year = year or date.today().year
    headers, rows = _rows_for_year(html, year)
    if not rows:
        raise ValueError(f"Treasury returned no {year} observations")
    output = []
    if table_type == "bill":
        bill_tenors = {"4": "treasury_4w_yield", "13": "treasury_13w_yield", "26": "treasury_26w_yield", "52": "treasury_52w_yield"}
        indexes = {}
        for tenor, series_key in bill_tenors.items():
            tenor_pattern = re.compile(rf"\b{tenor}\s+WEEKS?\b")
            for header_index, header in enumerate(headers):
                if not tenor_pattern.search(header):
                    continue
                combined = f"{tenor} WEEKS COUPON EQUIVALENT"
                if "COUPON EQUIVALENT" in header:
                    indexes[combined] = (series_key, header_index)
                elif header_index + 1 < len(headers):
                    indexes[combined] = (series_key, header_index + 1)
                break
        # Treasury's HTML has changed header markup more than once. The published
        # table keeps these bill maturities in fixed pairs after Date, 20Y, 30Y,
        # and Extrapolation Factor; use those documented table columns as fallback.
        if not indexes and rows and all(len(row) >= 18 for row in rows):
            indexes = {
                "4 WEEKS COUPON EQUIVALENT": (bill_tenors["4"], 5),
                "13 WEEKS COUPON EQUIVALENT": (bill_tenors["13"], 11),
                "26 WEEKS COUPON EQUIVALENT": (bill_tenors["26"], 15),
                "52 WEEKS COUPON EQUIVALENT": (bill_tenors["52"], 17),
            }
        wanted = {f"{tenor} WEEKS COUPON EQUIVALENT": key for tenor, key in bill_tenors.items()}
    else:
        wanted = {"3 MO": "treasury_3m_par", "1 YR": "treasury_1y_par", "2 YR": "treasury_2y_par", "10 YR": "treasury_10y_par"}
        indexes = {key: (series_key, headers.index(key)) for key, series_key in wanted.items() if key in headers}
    if not indexes:
        raise ValueError("Treasury columns did not match expected headings: " + " | ".join(headers[:20]))
    for row in rows:
        try:
            observed = datetime.strptime(row[0].strip(), "%m/%d/%Y").date().isoformat()
        except ValueError:
            continue
        for label, series_key in wanted.items():
            column = indexes.get(label)
            index = column[1] if column else None
            value = _float(row[index]) if index is not None and index < len(row) else None
            if value is not None:
                output.append({"series_key": series_key, "period": observed, "value": value, "unit": "percent annualized"})
    if not output:
        raise ValueError("Treasury table had no numeric yield observations")
    return output


def parse_census_timeseries(text: str, series_prefix: str) -> list[dict]:
    """Parse Census's tabular text file: monthly sales and seasonal factors."""
    normalized = text.replace("\xa0", " ")
    blocks = normalized.split("SEASONAL FACTORS")
    if len(blocks) != 2:
        raise ValueError("Census text file did not include its seasonal-factors section")
    months = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
    output = []
    for section_index, block in enumerate(blocks):
        for line in block.splitlines():
            match = re.match(r"^\s*(\d{4})\s+(.+?)\s*$", line)
            if not match:
                continue
            year = int(match.group(1))
            cells = re.findall(r"(?<!\S)(?:\d+(?:\.\d+)?|\.\d+)(?!\S)", match.group(2))
            if len(cells) < 6:
                continue
            for month_index, raw in enumerate(cells[:12], start=1):
                value = _float(raw)
                if value is None:
                    continue
                output.append({
                    "series_key": f"{series_prefix}_{'factor' if section_index else 'sales_sa'}",
                    "period": f"{year:04d}-{month_index:02d}",
                    "value": value,
                    "unit": "seasonal factor" if section_index else "million dollars, seasonally adjusted",
                })
    if not output:
        raise ValueError("Census file contained no monthly data")
    return output


def parse_eia_residential_gas(html: str) -> list[dict]:
    parser = _TableParser()
    parser.feed(html)
    output = []
    for table in parser.tables:
        for row in table:
            if len(row) < 13 or not re.fullmatch(r"\d{4}", row[0].strip()):
                continue
            year = int(row[0])
            for month, raw in enumerate(row[1:13], start=1):
                value = _float(raw)
                if value is not None:
                    output.append({"series_key": "eia_residential_gas", "period": f"{year:04d}-{month:02d}", "value": value, "unit": "million cubic feet"})
    if not output:
        raise ValueError("EIA natural-gas page contained no monthly observations")
    return output


def parse_eia_canada_oil(html: str) -> list[dict]:
    """Parse EIA monthly U.S. net imports of Canadian crude and products."""
    parser = _TableParser()
    parser.feed(html)
    output = []
    for table in parser.tables:
        for row in table:
            if len(row) < 13 or not re.fullmatch(r"\d{4}", row[0].strip()):
                continue
            year = int(row[0])
            for month, raw in enumerate(row[1:13], start=1):
                value = _float(raw)
                if value is not None:
                    output.append({"series_key": "eia_canada_net_imports", "period": f"{year:04d}-{month:02d}", "value": value, "unit": "thousand barrels per day"})
    if not output:
        raise ValueError("EIA Canada petroleum page contained no monthly observations")
    return output


def parse_bls_work_stoppages(html: str) -> list[dict]:
    """Parse BLS annual counts of major stoppages, workers and idle days."""
    parser = _TableParser()
    parser.feed(html)
    output = []
    for table in parser.tables:
        for row in table:
            if len(row) < 2 or not re.fullmatch(r"\d{4}", row[0].strip()):
                continue
            year = int(row[0])
            # The annual BLS factsheet table has year and count columns. The
            # detailed annual table also includes workers and idle days.
            metrics = [("bls_stoppages", 1, "stoppages")]
            if len(row) >= 6:
                metrics.extend([("bls_workers", 3, "thousand workers"), ("bls_idle_days", 5, "thousand workdays")])
            for key, index, unit in metrics:
                raw = re.match(r"\s*([\d,]+(?:\.\d+)?)", row[index])
                value = _float(raw.group(1)) if raw else None
                if value is not None:
                    output.append({"series_key": key, "period": str(year), "value": value, "unit": unit})
    if not output:
        raise ValueError("BLS annual table contained no work-stoppage observations")
    return output


def parse_bls_work_stoppages_api(payload: dict) -> list[dict]:
    """Parse official BLS monthly work-stoppage series WSU001 and WSU010."""
    if payload.get("status") != "REQUEST_SUCCEEDED":
        message = "; ".join(payload.get("message") or []) or "BLS API request failed"
        raise ValueError(message)
    series = (payload.get("Results") or {}).get("series") or []
    keys = {"WSU001": ("bls_idle_days", "thousand workdays"), "WSU010": ("bls_workers", "thousand workers")}
    output = []
    for item in series:
        key, unit = keys.get(item.get("seriesID"), (None, None))
        if not key:
            continue
        for point in item.get("data", []):
            year, period = point.get("year", ""), point.get("period", "")
            if not re.fullmatch(r"\d{4}", year) or not re.fullmatch(r"M(?:0[1-9]|1[0-2])", period):
                continue
            value = _float(point.get("value", ""))
            if value is not None:
                month = int(period[1:])
                output.append({"series_key": key, "period": f"{year}-{month:02d}", "value": value, "unit": unit})
    if not output:
        raise ValueError("BLS API contained no monthly work-stoppage observations")
    return output


def parse_eia_monthly_price(html: str, series_key: str, unit: str = "USD/barrel") -> list[dict]:
    parser = _TableParser()
    parser.feed(html)
    output = []
    for table in parser.tables:
        for row in table:
            if row:
                dated = re.fullmatch(r"(\d{4})[-/ ]([A-Za-z]{3}|\d{1,2})", row[0].strip())
                if dated:
                    month = int(dated.group(2)) if dated.group(2).isdigit() else {name.lower(): n for n, name in enumerate(("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), start=1)}.get(dated.group(2).lower())
                    value = _float(row[1]) if len(row) > 1 else None
                    if month and value is not None:
                        output.append({"series_key": series_key, "period": f"{int(dated.group(1)):04d}-{month:02d}", "value": value, "unit": unit})
                    continue
            if len(row) < 13 or not re.fullmatch(r"\d{4}", row[0].strip()):
                continue
            year = int(row[0])
            for month, raw in enumerate(row[1:13], start=1):
                value = _float(raw)
                if value is not None:
                    output.append({"series_key": series_key, "period": f"{year:04d}-{month:02d}", "value": value, "unit": unit})
    if not output:
        raise ValueError(f"EIA page contained no monthly observations for {series_key}")
    return output


def parse_eia_renewable_generation(html: str) -> list[dict]:
    """Read EIA Table 1.1.A: utility-scale renewables plus estimated small-scale solar."""
    parser = _TableParser()
    parser.feed(html)
    month_lookup = {name.lower(): number for number, name in enumerate(("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"), start=1)}
    month_lookup["sept"] = 9
    output = []
    for table in parser.tables:
        year = None
        for row in table:
            if not row:
                continue
            first = row[0].replace("\xa0", " ").strip()
            year_match = re.fullmatch(r"Year\s+(\d{4})", first, re.I)
            if year_match:
                year = int(year_match.group(1))
                continue
            if year is None or len(row) < 12:
                continue
            month = month_lookup.get(first.lower())
            if not month:
                continue
            values = [_float(value) for value in row[1:12]]
            if any(value is None for value in values):
                continue
            period = f"{year:04d}-{month:02d}"
            components = {
                "eia_renewable_generation": values[9] + values[10],
                "eia_renewable_wind": values[0],
                "eia_renewable_solar": values[1] + values[2] + values[10],
                "eia_renewable_hydro": values[8],
            }
            output.extend({"series_key": key, "period": period, "value": value, "unit": "thousand megawatthours"} for key, value in components.items())
    if not output:
        raise ValueError("EIA renewable generation table contained no monthly observations")
    return output


def fetch_sec_form4_feed(contact_email: str) -> str:
    """Fetch SEC filings using the real contact email required by SEC fair-access guidance."""
    if not contact_email or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", contact_email):
        raise ValueError("Set SEC_CONTACT_EMAIL to a real contact email so SEC can identify this app's requests")
    request = Request(SEC_FORM4_FEED, headers={"User-Agent": f"Investor Almanac/0.3 {contact_email}"})
    retryable_statuses = {408, 425, 429, 500, 502, 503, 504}
    for attempt in range(3):
        try:
            with urlopen(request, timeout=REQUEST_TIMEOUT) as response:
                return response.read().decode("utf-8-sig", errors="replace")
        except HTTPError as exc:
            if exc.code not in retryable_statuses or attempt == 2:
                raise
        except (URLError, TimeoutError, OSError):
            if attempt == 2:
                raise
        time.sleep(0.5 * (2 ** attempt))
    raise RuntimeError("SEC Form 4 request failed after retries")


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.hrefs.append(href)


def _xlsx_gold_silver(blob: bytes) -> list[dict]:
    """Read World Bank's small public monthly workbook without third-party packages."""
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main", "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships", "p": "http://schemas.openxmlformats.org/package/2006/relationships"}
    with zipfile.ZipFile(io.BytesIO(blob)) as book:
        strings = []
        if "xl/sharedStrings.xml" in book.namelist():
            root = ET.fromstring(book.read("xl/sharedStrings.xml"))
            strings = ["".join(node.itertext()) for node in root.findall("m:si", ns)]
        workbook = ET.fromstring(book.read("xl/workbook.xml"))
        sheet = next((node for node in workbook.findall("m:sheets/m:sheet", ns) if node.attrib.get("name") == "Monthly Prices"), None)
        if sheet is None:
            raise ValueError("World Bank workbook has no Monthly Prices sheet")
        relation_id = sheet.attrib[f"{{{ns['r']}}}id"]
        rels = ET.fromstring(book.read("xl/_rels/workbook.xml.rels"))
        target = next(node.attrib["Target"] for node in rels.findall("p:Relationship", ns) if node.attrib["Id"] == relation_id)
        path = target.lstrip("/") if target.startswith("/") else "xl/" + target
        root = ET.fromstring(book.read(path))
        rows = root.findall(".//m:sheetData/m:row", ns)
        decoded = []
        for row in rows:
            cells = {}
            for cell in row.findall("m:c", ns):
                ref = cell.attrib.get("r", "")
                col = re.match(r"[A-Z]+", ref)
                if not col:
                    continue
                value_node = cell.find("m:v", ns)
                if value_node is None:
                    continue
                value = value_node.text or ""
                if cell.attrib.get("t") == "s":
                    value = strings[int(value)]
                cells[col.group()] = value
            decoded.append(cells)
    header = next((row for row in decoded if "Gold" in row.values() and "Silver" in row.values()), None)
    if header is None:
        raise ValueError("World Bank workbook did not contain Gold and Silver columns")
    gold_col = next(col for col, value in header.items() if value == "Gold")
    silver_col = next(col for col, value in header.items() if value == "Silver")
    output = []
    for row in decoded:
        period = row.get("A", "")
        match = re.fullmatch(r"(\d{4})M(\d{2})", period.strip())
        if not match:
            continue
        month = f"{match.group(1)}-{match.group(2)}"
        for col, key in ((gold_col, "worldbank_gold"), (silver_col, "worldbank_silver")):
            value = _float(row.get(col, ""))
            if value is not None:
                output.append({"series_key": key, "period": month, "value": value, "unit": "USD/troy ounce"})
    if not output:
        raise ValueError("World Bank workbook had no monthly gold/silver observations")
    return output


def parse_conflict_rss(xml_text: str, max_items: int = 6) -> list[dict]:
    """Select current conflict-related headlines; this is keyword filtering, not verification."""
    import xml.etree.ElementTree as ET
    keywords = re.compile(r"\b(war|conflict|attack|fighting|ceasefire|invasion|military|airstrike|missile|troops|drone|shelling|offensive|bombing|armed group|hostage)\b", re.I)
    root = ET.fromstring(xml_text)
    items = []
    for item in root.findall(".//item"):
        title = unescape(" ".join((item.findtext("title") or "").split()))
        desc = unescape(" ".join(re.sub(r"<[^>]+>", " ", item.findtext("description") or "").split()))[:500]
        url = (item.findtext("link") or "").strip()
        published = (item.findtext("pubDate") or "").strip()
        if title and url.startswith("https://") and keywords.search(title + " " + desc):
            items.append({"title": title, "summary": desc, "url": url, "published": published})
        if len(items) >= max_items:
            break
    return items


def parse_sec_form4_atom(xml_text: str, max_items: int = 6) -> list[dict]:
    """Parse SEC's official current-Form-4 Atom feed without inferring transaction direction."""
    root = ET.fromstring(xml_text)
    entries = []
    for entry in root.iter():
        if entry.tag.rsplit("}", 1)[-1] != "entry":
            continue
        fields = {child.tag.rsplit("}", 1)[-1]: child for child in entry}
        title = " ".join((fields.get("title").text or "").split()) if fields.get("title") is not None else ""
        summary = " ".join(" ".join(fields["summary"].itertext()).split()) if fields.get("summary") is not None else ""
        published = ""
        for field in ("updated", "published"):
            if fields.get(field) is not None and fields[field].text:
                published = fields[field].text.strip()
                break
        url = ""
        for child in entry:
            if child.tag.rsplit("}", 1)[-1] == "link" and child.attrib.get("href"):
                url = child.attrib["href"]
                if child.attrib.get("rel", "alternate") == "alternate":
                    break
        if title and url.startswith("https://www.sec.gov/"):
            entries.append({"title": title, "summary": summary[:500], "url": url, "published": published})
        if len(entries) >= max_items:
            break
    return entries


def parse_eia_gasoline(html: str, today: date | None = None) -> list[dict]:
    today = today or date.today()
    parser = _TableParser()
    parser.feed(html)
    output = []
    month_lookup = {name.lower(): number for number, name in enumerate(("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), start=1)}
    for table in parser.tables:
        for row in table:
            match = re.fullmatch(r"(\d{4})-([A-Za-z]{3})", row[0].strip()) if row else None
            if not match:
                continue
            year, month_name = int(match.group(1)), match.group(2).lower()
            month = month_lookup.get(month_name)
            if not month:
                continue
            for index in range(1, len(row) - 1, 2):
                day_match = re.fullmatch(r"\d{2}/(\d{2})", row[index].strip())
                value = _float(row[index + 1])
                if not day_match or value is None:
                    continue
                try:
                    observed = date(year, month, int(day_match.group(1)))
                except ValueError:
                    continue
                if observed <= today:
                    output.append({"series_key": "eia_gasoline", "period": observed.isoformat(), "value": value, "unit": "thousand barrels per day"})
    if not output:
        raise ValueError("EIA gasoline page contained no weekly observations")
    return output


def source_observations(source_key: str, today: date | None = None) -> list[dict]:
    today = today or date.today()
    if source_key == "irs_filing_stats":
        return parse_irs_filing_statistics(_fetch(IRS_FILING_STATS))
    if source_key in FRED_INDEX_SERIES:
        return fetch_fred_index(source_key, today)
    if source_key in ("treasury_bills", "treasury_curve"):
        table_type = "daily_treasury_bill_rates" if source_key == "treasury_bills" else "daily_treasury_yield_curve"
        url = TREASURY_TEXT + "?" + urlencode({"field_tdr_date_value": str(today.year), "type": table_type})
        return parse_treasury(_fetch(url), "bill" if source_key == "treasury_bills" else "curve", today.year)
    if source_key.startswith("census_"):
        prefix = source_key.removeprefix("census_")
        return parse_census_timeseries(_fetch(SOURCES[source_key]["url"]), f"census_{prefix}")
    if source_key == "eia_residential_gas":
        return parse_eia_residential_gas(_fetch(EIA_GAS))
    if source_key == "eia_gasoline":
        return parse_eia_gasoline(_fetch(EIA_GASOLINE), today)
    if source_key == "eia_canada_oil":
        return parse_eia_canada_oil(_fetch(EIA_CANADA_OIL))
    if source_key == "bls_work_stoppages":
        import json
        end_year = today.year
        start_year = end_year - 9
        body = json.dumps({"seriesid": ["WSU001", "WSU010"], "startyear": str(start_year), "endyear": str(end_year)}).encode("utf-8")
        request = Request(BLS_API, data=body, headers={"Content-Type": "application/json", "User-Agent": "InvestorAlmanac/0.3 (self-hosted educational project)"})
        retryable_statuses = {408, 425, 429, 500, 502, 503, 504}
        for attempt in range(3):
            try:
                with urlopen(request, timeout=REQUEST_TIMEOUT) as response:
                    return parse_bls_work_stoppages_api(json.loads(response.read().decode("utf-8")))
            except HTTPError as exc:
                if exc.code not in retryable_statuses or attempt == 2:
                    raise
            except (URLError, TimeoutError, OSError):
                if attempt == 2:
                    raise
            time.sleep(0.5 * (2 ** attempt))
        raise RuntimeError("BLS API request failed after retries")
    energy_sources = {"eia_wti": (EIA_WTI_DATA, "USD/barrel"), "eia_brent": (EIA_BRENT, "USD/barrel"), "eia_henry_hub": (EIA_HENRY_HUB, "USD/MMBtu")}
    if source_key in energy_sources:
        url, unit = energy_sources[source_key]
        return parse_eia_monthly_price(_fetch(url), source_key, unit)
    if source_key == "worldbank_metals":
        links = _Links()
        links.feed(_fetch(WORLD_BANK_COMMODITIES))
        workbook_url = next((href if href.startswith("http") else "https://www.worldbank.org" + href for href in links.hrefs if "CMO-Historical-Data-Monthly.xlsx" in href), None)
        if not workbook_url:
            raise ValueError("World Bank commodity page did not link its monthly workbook")
        return _xlsx_gold_silver(_fetch_bytes(workbook_url))
    if source_key == "eia_renewable_power":
        return parse_eia_renewable_generation(_fetch(EIA_RENEWABLES))
    if source_key == "bbc_conflict_news":
        raise ValueError("BBC headlines are refreshed as a news feed, not numeric observations")
    raise KeyError(f"Unknown public data source: {source_key}")


def retrieved_at() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
