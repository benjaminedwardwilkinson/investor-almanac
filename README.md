# Investor Almanac

Investor Almanac is a self-hosted, playful calendar of market history and real-world seasons. Collectible-style field cards pair public evidence with plain-English context. It is for entertainment and education, not a trading system.

## Run on a Raspberry Pi

Install Docker Engine and Docker Compose, copy this folder to the Pi, then run:

```sh
docker compose up -d --build
```

Open `http://<pi-address>:8081`. There is no paid feed or edited CSV. The S&P 500, Dow, and Nasdaq cards download ten years of daily history from FRED and need a free API key. Put it in the Pi's private Compose `.env` file as `FRED_API_KEY=...`. Keep that key out of source files and the public website. Optional SEC Form 4 refresh uses `SEC_CONTACT_EMAIL` in the same `.env` file; without it, the app still shows official filing links and selected public examples. Port 8081 on the Pi maps to 8080 in the container, preserving other services on ports 80 and 8080.

SQLite data persists in the `stock-almanac-data` Docker volume. To stop the app, run `docker compose down`; the volume remains. To remove cached data too, explicitly remove that volume with `docker volume rm stock-almanac-master-product-engineering-specification_stock-almanac-data` (Compose may prefix the volume with the project name).

## The cards

- Ten years of daily S&P 500, Dow Jones Industrial Average, and NASDAQ Composite index levels. Each gets its own 1-, 5-, and 10-year price change; these are not live quotes and do not include dividends.
- Treasury bill yields and the yield curve as cash and rate context.
- Census retail seasonal factors around school shopping, holiday shopping, and spring home and garden activity.
- EIA natural-gas use, gasoline supplied, crude and gas benchmarks, Canadian petroleum trade, and renewable electricity generation.
- World Bank monthly gold and silver benchmarks.
- IRS weekly cumulative refund totals during tax season, from its free public CSV; refund totals are household cash-flow context, not a retail-spending or market-return measure.
- USDA weekly planting and harvest reports, with the current report linked from the card; NHC Atlantic hurricane climatology and live advisories; and CMS Medicare open-enrollment dates.
- BLS work-stoppage measures, BBC World conflict headlines, and links to public SEC, House, Senate, and OGE filings.
- Traditional sayings, table wisdom, and verified investor quotations tucked into related cards.

Numeric public data and headlines are cached in SQLite and refreshed daily or on request. Brief network failures are retried; failed sources are checked again about every 15 minutes. When a source is unavailable, the app keeps its last good cached values and reports the issue. The crop, hurricane, and Medicare cards also act as date-driven calendar guides and link directly to their official public sources.

## Read the numbers carefully

The app describes economic data and possible connections. It does not prove that an event caused a result or that an investment will benefit. Conflict cards are context, not investment opportunities. Census seasonal factors combine seasonal, holiday, and trading-day effects; they do not isolate holiday shopping. Gasoline product supplied is a demand proxy, residential gas use includes more than heating, and BLS major stoppages cover only large events and are released with a lag. Some economic series are revised and their release dates differ. This is not a point-in-time replay of what was known on a past date.

**Index-data terms:** FRED says the S&P 500 and Dow Jones series are third-party copyrighted and require prior approval for reproduction; Nasdaq's series is also copyrighted. FRED's API is free but requires a registered key. Keep this use noncommercial, retain the source attribution, and obtain the index providers' permission before presenting the index values on a public site. See the [FRED API key rules](https://fred.stlouisfed.org/docs/api/api_key.html) and [FRED terms](https://fred.stlouisfed.org/legal/terms/).

Price-index changes exclude dividends and do not represent an investor's full return. The three index point values are not comparable with each other. Historical patterns do not predict future results. There is no individual-stock price feed, live quote, trading signal, AI, or portfolio personalization.

SEC Form 4s can describe grants, options, gifts, planned transactions, and open-market trades. Congressional disclosures may arrive up to 45 days later and may show value ranges. Presidential annual disclosures and BlackRock 13F holdings are different records, not live trade feeds.

## Development

```sh
python -m pip install -r requirements.txt
python app.py
```

Then open `http://localhost:8080`.
