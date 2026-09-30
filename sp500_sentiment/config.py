"""Fixed values from the specification."""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

TIMEZONE = ZoneInfo("America/New_York")
AS_OF = datetime(2026, 9, 29, 0, 0, tzinfo=TIMEZONE)

# Article dates are local New York time, e.g. 2026-08-25T06:53.
DATE_FORMAT = "%Y-%m-%dT%H:%M"

NEWS_FIELDS = ("id", "date", "headline", "body")
SP500_COLUMNS = ("symbol", "security", "gics_sector", "headquarters", "date_added")

DATA_DIR = Path("data")
NEWS_PATH = DATA_DIR / "news.json"
SP500_PATH = DATA_DIR / "sp500.csv"
