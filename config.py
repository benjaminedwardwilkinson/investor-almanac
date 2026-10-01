"""Small defaults for the Investor Almanac home-server app."""

import os


PORT = int(os.environ.get("PORT", "8080"))
DATA_DIR = os.environ.get("DATA_DIR", "/data")
DATABASE = os.path.join(DATA_DIR, "stockalmanac.db")
REFRESH_HOURS = 24
REFRESH_RETRY_MINUTES = 15
REFRESH_CHECK_MINUTES = 5
REQUEST_TIMEOUT = 35
SEC_CONTACT_EMAIL = os.environ.get("SEC_CONTACT_EMAIL", "").strip()
FRED_API_KEY = os.environ.get("FRED_API_KEY", "").strip()
