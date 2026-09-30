"""Read the raw input files as they are: no cleaning, no validation.

A UTF-8 byte order mark is tolerated so that the file can still be parsed;
the audit reports it separately from the raw bytes.
"""

import csv
import io
import json
from pathlib import Path


def read_text(path: Path) -> str:
    return Path(path).read_bytes().decode("utf-8-sig")


def load_news(path: Path):
    """Parsed JSON content of news.json, whatever its shape."""
    return json.loads(read_text(path))


def load_sp500(path: Path) -> tuple[list[str], list[list[str]]]:
    """Header and data rows of sp500.csv, cells kept as raw strings."""
    rows = list(csv.reader(io.StringIO(read_text(path), newline="")))
    if not rows:
        return [], []
    return rows[0], rows[1:]
