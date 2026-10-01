"""Turn curated real-world events and cached data into transparent Almanac cards."""

from __future__ import annotations

import calendar
import statistics
from datetime import date, datetime, timedelta

from content import CARDS


MONTH_NAMES = list(calendar.month_name)[1:]


def _month_span(event: dict, year: int) -> tuple[date, date] | None:
    if not event["start"]:
        return None
    start = date(year, *event["start"])
    end_year = year + (1 if event["end"] < event["start"] else 0)
    end = date(end_year, *event["end"])
    return start, end


def event_state(event: dict, today: date) -> dict:
    if not event["start"]:
        return {"state": "all year", "days_until": None}
    windows = [_month_span(event, year) for year in range(today.year - 1, today.year + 2)]
    active = next(((start, end) for start, end in windows if start <= today <= end), None)
    if active:
        return {"state": "in season", "days_until": 0}
    future = [start for start, _ in windows if start > today]
    days = (min(future) - today).days if future else None
    return {"state": "coming soon" if days is not None and days <= 60 else "seasonal note", "days_until": days}


def _mean_monthly_factor(series: list[dict], months: list[int], today: date) -> dict:
    last_full_year = today.year - 1
    cutoff = last_full_year - 9
    observations = []
    by_month = {month: [] for month in range(1, 13)}
    for row in series:
        try:
            year_text, month_text = row["period"].split("-")
            year, month = int(year_text), int(month_text)
        except (ValueError, AttributeError):
            continue
        if cutoff <= year <= last_full_year:
            by_month[month].append((year, float(row["value"])))
            if month in months:
                observations.append((year, month, float(row["value"])))
    points = []
    for month, values in by_month.items():
        selected = [value for year, value in values]
        points.append({"label": calendar.month_abbr[month], "month": month, "value": round(statistics.mean(selected), 3) if selected else None})
    grouped = []
    for month in months:
        vals = [value for _, m, value in observations if m == month]
        grouped.append({"label": calendar.month_name[month], "value": round(statistics.mean(vals), 3) if vals else None, "years": len(vals)})
    return {"by_month": points, "selected_months": grouped, "years": f"{cutoff}–{last_full_year}"}


def _latest(series: list[dict]) -> dict | None:
    return series[-1] if series else None


def _cash_metrics(data: dict[str, list[dict]]) -> dict:
    keys = [("4-week", "treasury_4w_yield"), ("13-week", "treasury_13w_yield"), ("26-week", "treasury_26w_yield"), ("52-week", "treasury_52w_yield")]
    values = []
    for label, key in keys:
        item = _latest(data.get(key, []))
        if item:
            values.append({"label": label, "value": item["value"], "unit": "%", "date": item["period"]})
    current = next((item for item in values if item["label"] == "13-week"), None)
    fallback = False
    if not current:
        proxy = _latest(data.get("treasury_3m_par", []))
        if proxy:
            current = {"label": "3-month par yield", "value": float(proxy["value"]), "unit": "%", "date": proxy["period"]}
            values.append(current)
            fallback = True
    if current:
        current["headline"] = f"{current['value']:.2f}%"
        current["caption"] = (
            f"13-week Treasury bill coupon-equivalent yield · {current['date']}"
            if not fallback else f"T-bill feed unavailable · 3-month Treasury par-yield proxy · {current['date']}"
        )
    return {"headline": current["headline"] if current else "Waiting for Treasury data", "caption": current["caption"] if current else "Official rates load automatically on first run.", "values": values, "chart": values}


def _curve_metrics(data: dict[str, list[dict]]) -> dict:
    keys = [("3-month", "treasury_3m_par"), ("1-year", "treasury_1y_par"), ("2-year", "treasury_2y_par"), ("10-year", "treasury_10y_par")]
    values = []
    for label, key in keys:
        item = _latest(data.get(key, []))
        if item:
            values.append({"label": label, "value": item["value"], "unit": "%", "date": item["period"]})
    short = next((row["value"] for row in values if row["label"] == "3-month"), None)
    long = next((row["value"] for row in values if row["label"] == "10-year"), None)
    spread = round((long - short) * 100, 0) if short is not None and long is not None else None
    return {"headline": f"{spread:+.0f} bp" if spread is not None else "Waiting for Treasury data", "caption": "10-year minus 3-month Treasury par yield · basis points", "values": values, "chart": values}


def _gas_metrics(series: list[dict], today: date) -> dict:
    recent = []
    for row in series:
        try:
            when = date.fromisoformat(row["period"])
        except ValueError:
            continue
        if when <= today:
            recent.append((when, float(row["value"])))
    recent.sort()
    last = recent[-4:]
    current_avg = statistics.mean(value for _, value in last) if last else None
    year_ago_values = []
    for current_date, _ in last:
        target = current_date - timedelta(days=364)
        match = min(recent, key=lambda item: abs((item[0] - target).days)) if recent else None
        if match and abs((match[0] - target).days) <= 14:
            year_ago_values.append(match[1])
    comparison = statistics.mean(year_ago_values) if year_ago_values else None
    change = (current_avg / comparison - 1) * 100 if current_avg is not None and comparison else None
    return {
        "headline": f"{current_avg / 1000:.2f} million" if current_avg is not None else "Waiting for EIA data",
        "caption": "4-week average gasoline product supplied · million barrels per day",
        "change": round(change, 1) if change is not None else None,
        "latest_date": last[-1][0].isoformat() if last else None,
        "values": [{"label": when.strftime("%b %d"), "value": round(value / 1000, 3), "unit": "million barrels/day", "date": when.isoformat()} for when, value in recent[-12:]],
        "chart": [{"label": when.strftime("%b %d"), "value": round(value / 1000, 3)} for when, value in recent[-12:]],
    }


def _residential_gas_metrics(series: list[dict], today: date) -> dict:
    cutoff = today.year - 1
    monthly = _mean_monthly_factor(series, list(range(1, 13)), today)
    observed = []
    for row in series:
        try:
            year, month = (int(part) for part in row["period"].split("-"))
        except (ValueError, AttributeError):
            continue
        if date(year, month, 1) < today.replace(day=1):
            observed.append((year, month, float(row["value"])))
    observed.sort()
    latest = observed[-1] if observed else None
    previous = next((row for row in reversed(observed) if latest and row[0] == latest[0] - 1 and row[1] == latest[1]), None)
    yoy = (latest[2] / previous[2] - 1) * 100 if latest and previous and previous[2] else None
    seasonal = {point["month"]: point["value"] for point in monthly["by_month"] if point["value"] is not None}
    peak_months = sorted(seasonal, key=seasonal.get, reverse=True)[:2]
    headline = f"{latest[2] / 1_000_000:.2f} Tcf" if latest else "Waiting for EIA data"
    label = f"{calendar.month_name[latest[1]]} {latest[0]} residential use" if latest else "Monthly residential use"
    return {
        "headline": headline,
        "caption": f"{label} · {yoy:+.1f}% year over year" if yoy is not None else label,
        "change": round(yoy, 1) if yoy is not None else None,
        "latest_date": f"{latest[0]:04d}-{latest[1]:02d}" if latest else None,
        "peak_months": [calendar.month_name[month] for month in peak_months],
        "years": monthly["years"],
        "chart": monthly["by_month"],
        "values": [{"label": calendar.month_name[month], "value": round(value / 1_000_000, 2), "unit": "trillion cubic feet"} for month, value in seasonal.items()],
    }


def _labor_metrics(data: dict[str, list[dict]]) -> dict:
    by_key = {key: sorted(data.get(key, []), key=lambda row: row["period"]) for key in ("bls_stoppages", "bls_workers", "bls_idle_days")}
    stoppages = by_key["bls_stoppages"]
    if stoppages:
        latest = stoppages[-1]
        year = latest["period"]
        lookup = {key: next((row for row in reversed(rows) if row["period"] == year), None) for key, rows in by_key.items()}
        workers, idle = lookup["bls_workers"], lookup["bls_idle_days"]
        values = [{"label": "Stoppages beginning", "value": latest["value"], "unit": "stoppages", "years": year}]
        if workers:
            values.append({"label": "Workers involved", "value": workers["value"], "unit": "thousand workers", "years": year})
        if idle:
            values.append({"label": "Days idle", "value": idle["value"], "unit": "thousand workdays", "years": year})
        return {"headline": f"{latest['value']:,.0f} major stoppages", "caption": f"BLS annual count · {year}; workers involved: {workers['value']:,.1f} thousand" if workers else f"BLS annual count · {year}", "values": values, "chart": [{"label": row["period"], "value": row["value"]} for row in stoppages[-15:]], "latest_date": year}
    workers, idle = by_key["bls_workers"], by_key["bls_idle_days"]
    if not workers and not idle:
        return {"headline": "Waiting for BLS data", "caption": "Monthly major-stoppage measures · BLS series update with a lag", "values": [], "chart": []}
    latest = workers[-1] if workers else idle[-1]
    period = latest["period"]
    worker_row = next((row for row in reversed(workers) if row["period"] == period), None)
    idle_row = next((row for row in reversed(idle) if row["period"] == period), None)
    values = []
    if worker_row:
        values.append({"label": "Workers involved in stoppages beginning this month", "value": worker_row["value"], "unit": "thousand workers", "years": period})
    if idle_row:
        values.append({"label": "Workdays idled in stoppages active this month", "value": idle_row["value"], "unit": "thousand workdays", "years": period})
    return {"headline": f"{worker_row['value']:,.1f} thousand workers" if worker_row else f"{idle_row['value']:,.1f} thousand workdays idled", "caption": f"BLS monthly measures · {period}; stoppages involving at least 1,000 workers", "values": values, "chart": [{"label": row["period"], "value": row["value"]} for row in workers[-24:]], "latest_date": period}


def _canada_energy_metrics(series: list[dict]) -> dict:
    rows = sorted(series, key=lambda row: row["period"])
    if not rows:
        return {"headline": "Waiting for EIA data", "caption": "Monthly U.S. net imports of Canadian crude oil and petroleum products", "values": [], "chart": []}
    latest = rows[-1]
    year, month = (int(part) for part in latest["period"].split("-"))
    same_month = [row["value"] for row in rows if int(row["period"].split("-")[1]) == month and int(row["period"].split("-")[0]) < year]
    seasonal = statistics.mean(same_month[-10:]) if same_month else None
    caption = f"{latest['period']} · thousand barrels per day, net imports from Canada"
    if seasonal is not None:
        caption += f" · same-month history: {seasonal:,.0f}"
    return {"headline": f"{latest['value']:,.0f} thousand bbl/day", "caption": caption, "values": [{"label": "Latest month", "value": latest["value"], "unit": "thousand barrels per day", "years": latest["period"]}, *([{"label": f"{calendar.month_name[month]} historical average", "value": round(seasonal, 1), "unit": "thousand barrels per day", "years": f"prior {min(10, len(same_month))} years"}] if seasonal is not None else [])], "chart": [{"label": row["period"], "value": row["value"]} for row in rows[-24:]], "latest_date": latest["period"]}


def _benchmark_metrics(data: dict[str, list[dict]], keys: list[tuple[str, str]]) -> dict:
    values, latest_dates = [], []
    for label, key in keys:
        rows = sorted(data.get(key, []), key=lambda row: row["period"])
        if not rows:
            continue
        latest = rows[-1]
        previous = next((row for row in reversed(rows[:-1]) if row["period"] == f"{int(latest['period'][:4]) - 1:04d}{latest['period'][4:] }"), None)
        yoy = (float(latest["value"]) / float(previous["value"]) - 1) * 100 if previous and previous["value"] else None
        values.append({"label": label, "value": round(float(latest["value"]), 3), "unit": latest.get("unit", ""), "years": latest["period"], "change": round(yoy, 1) if yoy is not None else None})
        latest_dates.append(latest["period"])
    if not values:
        return {"headline": "Waiting for public data", "caption": "Monthly benchmark prices · latest observations may differ by release date", "values": [], "chart": []}
    short_units = {"USD/barrel": "bbl", "USD/MMBtu": "MMBtu", "USD/troy ounce": "oz"}
    headline = " · ".join(f"{item['label']} ${item['value']:,.2f}/{short_units.get(item['unit'], item['unit'])}" for item in values)
    return {"headline": headline, "caption": "Latest monthly EIA benchmark · nominal prices; not company earnings", "values": values, "chart": [], "latest_date": max(latest_dates)}


def _market_averages_metrics(data: dict[str, list[dict]], today: date) -> dict:
    """Summarize ten-year index histories using price-only returns at fixed horizons."""
    definitions = [
        ("S&P 500", "fred_sp500"),
        ("Dow Jones", "fred_djia"),
        ("NASDAQ Composite", "fred_nasdaq_composite"),
    ]
    markets = []
    for label, key in definitions:
        try:
            history_start = today.replace(year=today.year - 10)
        except ValueError:
            history_start = today.replace(year=today.year - 10, day=28)
        rows = sorted((row for row in data.get(key, []) if history_start.isoformat() <= row.get("period", "") <= today.isoformat()), key=lambda row: row["period"])
        if not rows:
            continue
        latest = rows[-1]
        latest_date = date.fromisoformat(latest["period"])
        history = []
        for years in (1, 5, 10):
            try:
                target = latest_date.replace(year=latest_date.year - years)
            except ValueError:
                target = latest_date.replace(year=latest_date.year - years, day=28)
            start = next((row for row in reversed(rows) if row["period"] <= target.isoformat()), None)
            change = None
            if start and float(start["value"]):
                change = round((float(latest["value"]) / float(start["value"]) - 1) * 100, 1)
            history.append({"years": years, "change": change})
        markets.append({
            "name": label,
            "level": round(float(latest["value"]), 2),
            "date": latest["period"],
            "observations": len(rows),
            "history": history,
        })
    if not markets:
        return {"headline": "Waiting for index history", "caption": "Daily closes · FRED · configure the free FRED_API_KEY", "values": [], "markets": [], "chart": []}
    latest_date = min(item["date"] for item in markets)
    ready = len(markets)
    summary = " · ".join(f"{item['name']} {item['level']:,.2f}" for item in markets)
    return {
        "headline": f"{ready}/3 averages · {latest_date}",
        "caption": summary,
        "markets": markets,
        "values": [
            {"label": f"{item['name']} close", "value": item["level"], "unit": "index points", "years": item["date"]}
            for item in markets
        ],
        "chart": [],
        "latest_date": latest_date,
        "note": "Price-index changes exclude dividends. Each index is compared with its own close on or just before the matching date.",
    }


def _irs_refund_metrics(data: dict[str, list[dict]], today: date) -> dict:
    amounts = sorted(
        (row for row in data.get("irs_refund_amount", []) if row.get("period", "") <= today.isoformat()),
        key=lambda row: row["period"],
    )
    if not amounts:
        return {"headline": "Waiting for IRS filing data", "caption": "The IRS weekly filing-season statistics load automatically.", "values": [], "chart": []}
    latest = amounts[-1]
    latest_date = date.fromisoformat(latest["period"])
    prior = [row for row in amounts if date.fromisoformat(row["period"]).year == latest_date.year - 1]
    comparison_date = latest_date.replace(year=latest_date.year - 1)
    prior_match = min(prior, key=lambda row: abs((date.fromisoformat(row["period"]) - comparison_date).days), default=None)
    change = None
    if prior_match and abs((date.fromisoformat(prior_match["period"]) - comparison_date).days) <= 10 and float(prior_match["value"]):
        change = round((float(latest["value"]) / float(prior_match["value"]) - 1) * 100, 1)
    values = [{"label": "Cumulative refunds issued", "value": round(float(latest["value"]), 2), "unit": "billion USD", "date": latest["period"]}]
    average = next((row for row in data.get("irs_refund_average", []) if row.get("period") == latest["period"]), None)
    count = next((row for row in data.get("irs_refund_count", []) if row.get("period") == latest["period"]), None)
    if average:
        values.append({"label": "Average refund", "value": round(float(average["value"])), "unit": "USD", "date": latest["period"]})
    if count:
        values.append({"label": "Refunds issued", "value": float(count["value"]), "unit": "refunds", "date": latest["period"]})
    return {
        "headline": f"${float(latest['value']):,.1f}B in refunds",
        "caption": f"Cumulative IRS refunds issued through {latest_date.strftime('%b %d, %Y')}" + (f" · {change:+.1f}% vs. a similar week last year" if change is not None else ""),
        "change": change,
        "latest_date": latest["period"],
        "values": values,
        "chart": [{"label": row["period"], "value": float(row["value"])} for row in amounts[-12:]],
    }


def _renewable_power_metrics(data: dict[str, list[dict]]) -> dict:
    rows = sorted(data.get("eia_renewable_generation", []), key=lambda row: row["period"])
    if not rows:
        return {"headline": "Waiting for EIA generation data", "caption": "Monthly U.S. renewable electricity generation", "values": [], "chart": []}
    latest = rows[-1]
    year, month = latest["period"].split("-")
    previous = next((row for row in reversed(rows[:-1]) if row["period"] == f"{int(year) - 1:04d}-{month}"), None)
    change = (float(latest["value"]) / float(previous["value"]) - 1) * 100 if previous and previous["value"] else None
    values = [{"label": "Renewable electricity", "value": round(float(latest["value"]) / 1000, 1), "unit": "TWh", "years": latest["period"], "change": round(change, 1) if change is not None else None}]
    for key, label in (("eia_renewable_wind", "Wind"), ("eia_renewable_solar", "Solar"), ("eia_renewable_hydro", "Hydropower")):
        component = next((row for row in data.get(key, []) if row["period"] == latest["period"]), None)
        if component:
            values.append({"label": label, "value": round(float(component["value"]) / 1000, 1), "unit": "TWh", "years": latest["period"]})
    return {
        "headline": f"{float(latest['value']) / 1000:,.1f} TWh from renewables",
        "caption": f"EIA monthly generation · {latest['period']} · utility renewables plus estimated small-scale solar; latest observations may be preliminary",
        "values": values,
        "change": round(change, 1) if change is not None else None,
        "chart": [{"label": row["period"], "value": row["value"]} for row in rows[-24:]],
        "latest_date": latest["period"],
    }


def _card_metric(card: dict, data: dict[str, list[dict]], today: date) -> dict:
    metric = card["metric"]
    if metric == "irs_refunds":
        return _irs_refund_metrics(data, today)
    if metric == "seasonal_context":
        return {"headline": card["metric_headline"], "caption": card["metric_caption"], "values": [], "chart": []}
    if metric == "market_averages":
        return _market_averages_metrics(data, today)
    if metric == "folk_wisdom":
        return {"headline": "Old sayings · fresh questions", "caption": "Folklore offers a lens for curiosity, not a market forecast."}
    if metric == "public_filings":
        return {"headline": "SEC · House · Senate", "caption": "Official searches for public ownership and transaction disclosures"}
    if metric == "public_filings":
        return {"headline": "SEC · House · Senate", "caption": "Official searches for public ownership and transaction disclosures"}
    if metric == "conflict_context":
        return {"headline": "Human impact first", "caption": "War can harm people, livelihoods, essential services, and businesses."}
    if metric == "cash":
        return _cash_metrics(data)
    if metric == "curve":
        return _curve_metrics(data)
    if metric == "driving":
        return _gas_metrics(data.get("eia_gasoline", []), today)
    if metric == "heating":
        return _residential_gas_metrics(data.get("eia_residential_gas", []), today)
    if metric == "labor":
        return _labor_metrics(data)
    if metric == "canada_energy":
        return _canada_energy_metrics(data.get("eia_canada_net_imports", []))
    if metric == "energy_benchmarks":
        return _benchmark_metrics(data, [("WTI crude", "eia_wti"), ("Brent crude", "eia_brent"), ("Henry Hub gas", "eia_henry_hub")])
    if metric == "renewable_power":
        return _renewable_power_metrics(data)
    if metric == "precious_metals":
        return _benchmark_metrics(data, [("Gold", "worldbank_gold"), ("Silver", "worldbank_silver")])
    factor_by_card = {
        "school": [("Clothing", "census_clothing_factor"), ("Electronics", "census_electronics_factor")],
        "holiday": [("General merchandise", "census_general_factor"), ("Online / nonstore", "census_nonstore_factor")],
        "home": [("Building & garden", "census_building_factor")],
    }
    selected_months = {"school": [8], "holiday": [11, 12], "home": [4, 5]}[metric]
    values = []
    histories = []
    for label, key in factor_by_card[metric]:
        result = _mean_monthly_factor(data.get(key, []), selected_months, today)
        histories.append({"label": label, "by_month": result["by_month"], "selected_months": result["selected_months"]})
        for point in result["selected_months"]:
            values.append({"label": f"{label} · {point['label']}", "value": point["value"], "unit": "seasonal factor", "years": point["years"]})
    valid = [row["value"] for row in values if row["value"] is not None]
    headline = f"{statistics.mean(valid):.3f}" if valid else "Waiting for Census data"
    source_years = _mean_monthly_factor(data.get(factor_by_card[metric][0][1], []), selected_months, today)["years"]
    return {
        "headline": headline,
        "caption": f"Average Census seasonal factor for the selected months · {source_years}",
        "values": values,
        "chart": histories,
        "years": source_years,
    }


def _opportunity_read(card: dict, metrics: dict) -> dict:
    """Translate economic context into a plain buy-side, sell-side, or mixed watch."""
    if card["metric"] == "irs_refunds":
        change = metrics.get("change")
        comparison = f"Cumulative refunds issued are {abs(change):.1f}% {'higher' if change > 0 else 'lower' if change < 0 else 'unchanged'} than around the same week last year." if change is not None else "The latest IRS figure is cumulative and may not yet have a same-week comparison."
        return {"label": "REFUND FLOW · HOUSEHOLD CASH CONTEXT", "detail": f"{comparison} Refund totals do not tell us whether households spend, save, or pay down debt, and they are not a market-return signal.", "benefit": "A useful seasonal reminder to look at how household cash flow can shift.", "pressure": "Tax rules, filing dates, and processing speed affect the totals; no asset buy or sell call follows from them."}
    if card["metric"] == "seasonal_context":
        reads = {
            "crop_progress": ("GROWING-SEASON WATCH · NO TRADE", "Planting and harvest are crop- and region-specific. USDA’s weekly report gives context; it does not establish a market direction."),
            "hurricane_season": ("COMMUNITY PREPAREDNESS · NO TRADE", "NOAA’s basin-wide climate averages describe past frequency, not a forecast for any coast, business, or investment."),
            "medicare_enrollment": ("COVERAGE REVIEW WINDOW · NO TRADE", "This annual deadline is a household coverage milestone, not evidence for buying or selling a healthcare investment."),
        }
        label, detail = reads.get(card["id"], ("SEASONAL NOTE · NO TRADE", "A recurring date can organize a question; it does not predict an investment result."))
        return {"label": label, "detail": detail, "benefit": "A timely prompt to learn about the event and its real-world context.", "pressure": "The calendar alone does not establish who benefits financially or how markets will respond."}
    if card["metric"] == "cash":
        short_bill = next((item for item in metrics.get("values", []) if item["label"] in {"13-week", "3-month par yield"}), None)
        if short_bill and short_bill.get("value", 0) > 0:
            tenor = "13-week T-bill" if short_bill["label"] == "13-week" else "3-month Treasury par-yield proxy"
            return {
                "label": "BUY-SIDE INCOME IDEA: short-term T-bills",
                "detail": f"The latest {tenor} yield is {short_bill['value']:.2f}% annualized. That is a positive nominal income opportunity—not proof it beats inflation or that every T-bill ETF is a buy.",
                "benefit": "T-bills offer short-term U.S. government debt exposure with a stated yield when held to maturity.",
            "pressure": "Inflation and taxes can reduce what that yield buys; ETF returns and payouts can differ from the quoted bill yield.",
        }
        return {
            "label": "T-BILL YIELD DATA PENDING",
            "detail": "The latest Treasury yield has not loaded, so the income opportunity cannot be assessed yet.",
            "benefit": "Short-term T-bills can provide nominal interest when yields are positive.",
            "pressure": "Compare the yield with inflation, taxes, and other uses for cash.",
        }
    if card["metric"] == "precious_metals":
        gold = next((item for item in metrics.get("values", []) if item["label"] == "Gold"), None)
        change = gold.get("change") if gold else None
        movement = f"Gold is {abs(change):.1f}% {'up' if change > 0 else 'down'} year over year. " if change is not None else "The cached series has no same-month comparison yet. "
        direction = "BUY-SIDE MOMENTUM WATCH" if change is not None and change > 0 else "SELL-SIDE MOMENTUM WATCH" if change is not None and change < 0 else "METALS TREND DATA PENDING"
        return {
            "label": direction,
            "detail": movement + "This is a simple trend read: it tells which way price moved, not whether gold is cheap or overvalued. Treat it as a momentum idea to research, not a tested entry rule.",
            "benefit": "Higher gold prices can improve miners’ revenue per ounce if output and costs hold. That does not establish that mining shares are bargains.",
            "pressure": "New bullion buyers face a higher price than a year ago when the price is up. That alone does not mean existing holders should sell.",
        }
    if card["metric"] == "energy_benchmarks":
        return {
            "label": "TWO-SIDED ENERGY OPPORTUNITY",
            "detail": "Energy prices create different opportunities across the chain: producers can benefit from higher selling prices while refiners and fuel users may face higher costs. Company share prices are not measured here.",
            "benefit": "Higher crude prices can help upstream producers if costs and production hold steady.",
            "pressure": "Higher crude prices can squeeze refiners and raise fuel costs; refining margins and contracts matter.",
        }
    if card["metric"] == "renewable_power":
        change = metrics.get("change")
        if change is None:
            return {"label": "RENEWABLE GENERATION DATA PENDING", "detail": "EIA’s monthly generation history has not loaded a same-month comparison yet.", "benefit": "The series provides a broad look at renewable electricity output.", "pressure": "Generation growth does not identify which companies earn a profit."}
        direction = "BUY-SIDE INDUSTRY TAILWIND" if change > 0 else "SELL-SIDE INDUSTRY HEADWIND" if change < 0 else "RENEWABLE OUTPUT STEADY"
        return {"label": f"{direction} · {abs(change):.1f}% Y/Y", "detail": f"U.S. renewable electricity generation was {abs(change):.1f}% {'higher' if change > 0 else 'lower' if change < 0 else 'unchanged'} than the same month a year earlier. That is an industry activity signal, not proof clean-energy shares are under- or overvalued.", "benefit": "Growing output can support demand for renewable generation, equipment, grid connections, and storage.", "pressure": "Financing costs, project delays, equipment prices, grid limits, incentives, and power contracts can outweigh output growth."}
    if card["metric"] in {"school", "holiday", "home"}:
        observed = [float(item["value"]) for item in metrics.get("values", []) if item.get("value") is not None]
        average = statistics.mean(observed) if observed else None
        category = {"school": "SCHOOL RETAIL", "holiday": "HOLIDAY RETAIL", "home": "HOME & GARDEN RETAIL"}[card["metric"]]
        if average is None:
            return {"label": f"{category} DATA PENDING", "detail": "Seasonal sales data has not loaded yet; no seasonal direction can be shown.", "benefit": "Related businesses are listed as exposure examples.", "pressure": "A seasonal sales pattern does not guarantee company profit or share-price gains."}
        direction = "BUY-SIDE SEASONAL TAILWIND" if average > 1 else "SELL-SIDE SEASONAL SOFT PATCH" if average < 1 else "NORMAL SEASONAL PATTERN"
        detail = f"The selected-month average seasonal factor is {average:.3f}. Above 1.0 means sales have historically run above trend in these months; below 1.0 means below trend. This is business seasonality, not a tested stock-return signal."
        return {"label": f"{direction} · {category}", "detail": detail, "benefit": "Retailers and related businesses may see stronger seasonal sales when the factor is above 1.0.", "pressure": "Sales patterns do not reveal profit margins, expectations already in share prices, or future returns."}
    if card["metric"] in {"driving", "heating"}:
        change = metrics.get("change")
        if change is None:
            return {"label": "ENERGY DEMAND DATA PENDING", "detail": "The data is not ready for a year-over-year demand direction yet.", "benefit": "Demand can affect suppliers and service businesses.", "pressure": "Prices, weather, supply, and margins can outweigh demand."}
        direction = "BUY-SIDE DEMAND TAILWIND" if change > 0 else "SELL-SIDE DEMAND SOFTNESS" if change < 0 else "STEADY DEMAND"
        subject = "gasoline product supplied" if card["metric"] == "driving" else "residential natural-gas use"
        return {"label": f"{direction} · {abs(change):.1f}% Y/Y", "detail": f"The latest {subject} measure is {abs(change):.1f}% {'higher' if change > 0 else 'lower' if change < 0 else 'unchanged'} year over year. This points to demand direction, not company profitability or investment returns.", "benefit": "Higher demand can be a business tailwind for some suppliers and service companies.", "pressure": "Lower demand can pressure volumes; consumers, weather, and prices also affect the outcome."}
    if card["metric"] == "labor":
        points = metrics.get("chart", [])
        if len(points) >= 2:
            change = float(points[-1]["value"]) - float(points[-2]["value"])
            label = "SELL-SIDE OPERATING PRESSURE" if change > 0 else "LESS LABOR DISRUPTION" if change < 0 else "LABOR DISRUPTION STEADY"
            return {"label": label, "detail": f"The annual count of major stoppages {'rose' if change > 0 else 'fell' if change < 0 else 'was unchanged'} by {abs(change):,.0f} from {points[-2]['label']} to {points[-1]['label']}. The aggregate, delayed series does not identify current company exposure.", "benefit": "Workers and communities are directly affected; firms without disruptions may face less operating interruption.", "pressure": "Affected employers can face lost output or added costs. The data does not support a broad stock sale call."}
        return {"label": "LABOR DISRUPTION WATCH", "detail": "The annual BLS count is a lagged measure of large stoppages, not a current industry-wide signal.", "benefit": "Review company and worker context before drawing conclusions.", "pressure": "Specific operating pressure depends on which employers and workers are involved."}
    if card["metric"] == "curve":
        return {"label": "TWO-SIDED RATE BACKDROP", "detail": "Current rates create different effects across cash, borrowers, and bond maturities; this card does not forecast which asset will outperform.", "benefit": "Short-term government debt offers a current yield to compare with alternatives.", "pressure": "Higher yields can weigh on existing bond prices and raise some borrowing costs."}
    if card["metric"] == "canada_energy":
        return {"label": "ENERGY SUPPLY-CHAIN WATCH", "detail": "Canadian petroleum flows can matter to connected refiners and infrastructure; the trade measure alone does not establish a buy or sell timing signal.", "benefit": "Reliable supply and throughput can matter to refiners and pipeline operators.", "pressure": "Policy, prices, pipeline capacity, and refinery configuration can change who benefits."}
    if card["metric"] == "conflict_context":
        return {"label": "HUMAN-IMPACT CONTEXT · NOT A TRADE", "detail": "The card follows current reporting to explain human and economic effects; it does not turn conflict into an investment opportunity.", "benefit": "No beneficiary call is made for war-related events.", "pressure": "The focus is on people, essential services, and communities affected."}
    if card["metric"] == "folk_wisdom":
        return {"label": "FOLK WISDOM · NOT A TRADE", "detail": "Traditional sayings are prompts for thoughtful questions, not evidence of a buy or sell opportunity.", "benefit": "Use them to check concentration, costs, and assumptions.", "pressure": "They are not tested market rules."}
    if card["metric"] == "public_filings":
        return {"label": "FOLLOW THE FILINGS · NOT THE FILER", "detail": "These official pages show disclosed reports. Filings may be delayed, incomplete, or about transactions other than open-market buys and sells.", "benefit": "Use the filing date, transaction code, filer role, and reported value range to understand what was actually disclosed.", "pressure": "A public official or executive’s reported transaction does not establish that the same investment suits you or will perform well."}
    if card["metric"] == "public_filings":
        return {"label": "FOLLOW THE FILINGS · NOT THE FILER", "detail": "These official pages show disclosed reports. Filings may be delayed, incomplete, or about transactions other than open-market buys and sells.", "benefit": "Use the filing date, transaction code, filer role, and reported value range to understand what was actually disclosed.", "pressure": "A public official or executive’s reported transaction does not establish that the same investment suits you or will perform well."}
    return {"label": "OPPORTUNITY WATCH", "detail": "This context can help identify what to research; it does not measure future investment returns.", "benefit": "Explore the economic channels described in the card.", "pressure": "Review the risks before treating a theme as an opportunity."}


def _calendar_month(event: dict, month: int, year: int) -> bool:
    if not event["start"]:
        return False
    month_start = date(year, month, 1)
    month_end = date(year, month, calendar.monthrange(year, month)[1])
    for span_year in (year - 1, year, year + 1):
        start, end = _month_span(event, span_year)
        if start <= month_end and end >= month_start:
            return True
    return False


def build_dashboard(data: dict[str, list[dict]], sources: list[dict], refresh: dict, today: date | None = None, news_stories: list[dict] | None = None, disclosure_stories: list[dict] | None = None) -> dict:
    today = today or date.today()
    cards = []
    for content in CARDS:
        position = event_state(content, today)
        card = {**content, **position, "metrics": _card_metric(content, data, today)}
        card["opportunity"] = _opportunity_read(content, card["metrics"])
        if content["metric"] == "conflict_context":
            card["stories"] = news_stories or []
            if news_stories:
                card["metrics"]["headline"] = f"{len(news_stories)} current headlines"
                card["metrics"]["caption"] = "BBC World feed · filtered by conflict-related keywords; stories vary over time"
            else:
                card["metrics"]["caption"] = "Headlines appear after the public RSS feed is fetched"
        if content["metric"] == "public_filings":
            card["stories"] = disclosure_stories or []
            card["stories_title"] = "Recent SEC Form 4 filings"
            if disclosure_stories:
                card["metrics"]["headline"] = f"{len(disclosure_stories)} recent Form 4 filings"
                card["metrics"]["caption"] = "SEC ownership reports · inspect the filing for the transaction code and details"
            else:
                card["metrics"]["caption"] = "Latest filings appear after the SEC feed is fetched"
        cards.append(card)
    months = {
        month: [
            {"id": card["id"], "name": card["name"], "icon": card["icon"]}
            for card in cards if not card["start"] or _calendar_month(card, month, today.year)
        ]
        for month in range(1, 13)
    }
    featured = [card for card in cards if card["state"] in {"all year", "in season", "coming soon"}]
    featured.sort(key=lambda card: (0 if card["state"] == "all year" else 1 if card["state"] == "in season" else 2, card["days_until"] if card["days_until"] is not None else 0))
    return {
        "date": today.isoformat(),
        "pretty_date": today.strftime("%A, %B %d, %Y").replace(" 0", " "),
        "month": today.month,
        "month_name": calendar.month_name[today.month],
        "cards": cards,
        "featured_ids": [card["id"] for card in featured],
        "calendar": months,
        "sources": sources,
        "refresh": refresh,
        "disclaimer": "For entertainment and education. These are exposure examples, not a signal to buy or sell.",
    }


def cards_for_month(dashboard: dict, month: int, year: int | None = None) -> list[dict]:
    year = year or date.today().year
    return [card for card in dashboard["cards"] if not card["start"] or _calendar_month(card, month, year)]
