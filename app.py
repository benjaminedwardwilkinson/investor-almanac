"""Flask application for Investor Almanac."""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Flask, jsonify, render_template

from almanac import build_dashboard
from config import DATABASE, PORT, REFRESH_CHECK_MINUTES, REFRESH_HOURS, REFRESH_RETRY_MINUTES, SEC_CONTACT_EMAIL
from public_data import SOURCES, retrieved_at, source_observations, parse_conflict_rss, parse_sec_form4_atom, fetch_sec_form4_feed, _fetch
from storage import all_series, init_db, save_error, save_source, save_news, recent_news, source_status


ROOT = Path(__file__).resolve().parent
app = Flask(__name__, template_folder=str(ROOT / "templates"), static_folder=str(ROOT / "static"))
_refresh_lock = threading.Lock()
_refresh_state = {"running": False, "started_at": None, "finished_at": None, "message": "Data refresh has not run in this process.", "errors": []}


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def refresh_due() -> bool:
    statuses = source_status()
    if not statuses:
        return True
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=REFRESH_HOURS)
    retry_cutoff = now - timedelta(minutes=REFRESH_RETRY_MINUTES)
    for item in statuses:
        if item.get("last_error") or not item.get("retrieved_at"):
            attempted = item.get("attempted_at")
            if not attempted:
                return True
            try:
                if datetime.fromisoformat(attempted) < retry_cutoff:
                    return True
            except ValueError:
                return True
            continue
        try:
            if datetime.fromisoformat(item["retrieved_at"]) < cutoff:
                return True
        except ValueError:
            return True
    return False


def _refresh_worker():
    succeeded, failures = 0, []
    try:
        for source_key, metadata in SOURCES.items():
            attempted = retrieved_at()
            try:
                if source_key in {"bbc_conflict_news", "sec_form4_feed"}:
                    feed_text = fetch_sec_form4_feed(SEC_CONTACT_EMAIL) if source_key == "sec_form4_feed" else _fetch(metadata["url"])
                    stories = parse_conflict_rss(feed_text) if source_key == "bbc_conflict_news" else parse_sec_form4_atom(feed_text)
                    count = save_news(source_key, metadata, stories, attempted, DATABASE)
                    succeeded += 1
                    print(f"[data] {source_key}: saved {count} headlines", flush=True)
                    continue
                observations = source_observations(source_key)
                count = save_source(source_key, metadata, observations, attempted, DATABASE)
                succeeded += 1
                print(f"[data] {source_key}: saved {count} observations", flush=True)
            except Exception as exc:  # Keep stale good values and report the failing source.
                message = f"{type(exc).__name__}: {str(exc)[:300]}"
                save_error(source_key, metadata, message, attempted, DATABASE)
                failures.append({"source": metadata["title"], "error": message})
                print(f"[data] {source_key}: {message}", flush=True)
    finally:
        _refresh_state.update({
            "running": False,
            "finished_at": _utcnow(),
            "errors": failures,
            "message": f"Updated {succeeded} of {len(SOURCES)} sources" + (f"; {len(failures)} need attention." if failures else "."),
        })
        with _refresh_lock:
            _refresh_state["running"] = False


def start_refresh(force: bool = False) -> bool:
    if not force and not refresh_due():
        return False
    with _refresh_lock:
        if _refresh_state["running"]:
            return False
        _refresh_state.update({"running": True, "started_at": _utcnow(), "message": "Refreshing official public data…", "errors": []})
        worker = threading.Thread(target=_refresh_worker, name="almanac-data-refresh", daemon=True)
        worker.start()
        return True


def _daily_refresh_loop():
    while True:
        threading.Event().wait(60 * REFRESH_CHECK_MINUTES)
        if refresh_due():
            start_refresh()


@app.get("/")
def home():
    return render_template("index.html")


@app.get("/api/health")
def health():
    return jsonify({"ok": True, "service": "investor-almanac"})


@app.get("/api/dashboard")
def dashboard():
    refresh = {**_refresh_state, "sources": len(SOURCES)}
    known = {item["source_key"]: item for item in source_status(DATABASE)}
    sources = [{"source_key": key, **metadata, **known.get(key, {})} for key, metadata in SOURCES.items()]
    return jsonify(build_dashboard(
        all_series(DATABASE), sources, refresh,
        news_stories=recent_news("bbc_conflict_news", db_path=DATABASE),
        disclosure_stories=recent_news("sec_form4_feed", db_path=DATABASE),
    ))


@app.post("/api/refresh")
def refresh():
    started = start_refresh(force=True)
    return jsonify({**_refresh_state, "started": started, "sources": len(SOURCES)}), 202 if started else 200


def main():
    init_db(DATABASE)
    start_refresh()
    threading.Thread(target=_daily_refresh_loop, name="almanac-daily-refresh", daemon=True).start()
    print(f"Investor Almanac listening on 0.0.0.0:{PORT}", flush=True)
    app.run(host="0.0.0.0", port=PORT, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
