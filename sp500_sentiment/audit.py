"""Read-only audit of the raw inputs (news.json and sp500.csv).

Usage: python -m sp500_sentiment.audit [--news PATH] [--sp500 PATH] [--out FILE]

Each check is one function returning a list of findings (one line of text each).
Nothing is fixed here and the input files are never modified.
"""

import argparse
import codecs
import hashlib
import json
import re
import statistics
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path

from sp500_sentiment import config, load

MAX_LINES = 30  # findings shown per section in the report
SHINGLE_WORDS = 5  # near-duplicates: Jaccard similarity of 5-word sequences
NEAR_DUPLICATE_MIN = 0.5

# --- Helpers -----------------------------------------------------------------

_ESCAPES = {"\n": "\\n", "\r": "\\r", "\t": "\\t", "\\": "\\\\", "`": "\\x60"}


def show(text: str) -> str:
    """Printable ASCII form of a text: anything else becomes an escape like \\u200b."""
    out = []
    for c in text:
        o = ord(c)
        if c in _ESCAPES:
            out.append(_ESCAPES[c])
        elif 32 <= o < 127:
            out.append(c)
        else:
            out.append(f"\\x{o:02x}" if o < 0x100 else f"\\u{o:04x}" if o < 0x10000 else f"\\U{o:08x}")
    return "".join(out)


def char_label(c: str) -> str:
    return f"U+{ord(c):04X} {unicodedata.name(c, 'unnamed')}"


def snippet(text: str, pos: int, width: int = 25) -> str:
    return show(text[max(0, pos - width) : pos + width])


def comparable(text: str) -> str:
    """Text reduced for duplicate detection: NFKC, no invisible characters, single spaces, casefolded."""
    text = unicodedata.normalize("NFKC", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Cf")
    return " ".join(text.split()).casefold()


def record_id(article, index: int) -> str:
    ident = article.get("id") if isinstance(article, dict) else None
    return show(ident) if isinstance(ident, str) and ident.strip() else f"record #{index}"


def news_records(news) -> list[tuple[str, dict]]:
    """(display id, article) for every record that is a JSON object."""
    if not isinstance(news, list):
        return []
    return [(record_id(a, i), a) for i, a in enumerate(news) if isinstance(a, dict)]


def news_texts(articles, field: str) -> list[tuple[str, str]]:
    return [(f"{rid} {field}", a[field]) for rid, a in articles if isinstance(a.get(field), str)]


def sp500_records(header, rows) -> list[tuple[int, dict]]:
    """(row number, cells by column name); the header is row 1."""
    return [(n, dict(zip(header, row))) for n, row in enumerate(rows, start=2)]


def sp500_texts(header, rows) -> list[tuple[str, str]]:
    return [(f"row {n} {show(col)}", cell) for n, row in enumerate(rows, start=2) for col, cell in zip(header, row)]


# --- File-level checks (both files) ------------------------------------------------


def check_file_bytes(data: bytes) -> list[str]:
    findings = []
    if data.startswith(codecs.BOM_UTF8):
        findings.append("UTF-8 byte order mark at the start of the file")
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as e:
        findings.append(f"invalid UTF-8 at byte {e.start}")
    crlf = data.count(b"\r\n")
    endings = {"LF": data.count(b"\n") - crlf, "CRLF": crlf, "CR": data.count(b"\r") - crlf}
    if endings["CR"] or sum(1 for n in endings.values() if n) > 1:
        findings.append("mixed line endings: " + ", ".join(f"{n} {k}" for k, n in endings.items()))
    return findings


def check_mojibake(texts) -> list[str]:
    """Runs of non-ASCII characters that read as UTF-8 bytes decoded as Windows-1252 (e.g. 'â€™')."""
    findings = []
    for where, text in texts:
        for m in re.finditer(r"[^\x00-\x7f]+", text):
            try:
                fixed = m.group().encode("cp1252").decode("utf-8")
            except UnicodeError:
                continue
            findings.append(f"{where}: `{show(m.group())}` looks like mis-decoded `{show(fixed)}`")
    return findings


# --- news.json: structure ---------------------------------------------------------


def check_news_structure(news) -> list[str]:
    if not isinstance(news, list):
        return [f"top level is {type(news).__name__}, expected a list"]
    findings = []
    for i, a in enumerate(news):
        if not isinstance(a, dict):
            findings.append(f"record #{i}: {type(a).__name__}, expected an object")
            continue
        rid = record_id(a, i)
        missing = [k for k in config.NEWS_FIELDS if k not in a]
        extra = [show(k) for k in a if k not in config.NEWS_FIELDS]
        if missing:
            findings.append(f"{rid}: missing keys {missing}")
        if extra:
            findings.append(f"{rid}: unexpected keys {extra}")
        for k in config.NEWS_FIELDS:
            if k not in a:
                continue
            if not isinstance(a[k], str):
                findings.append(f"{rid} {k}: {type(a[k]).__name__} value `{show(repr(a[k]))[:60]}`, expected a string")
            elif not a[k].strip():
                findings.append(f"{rid} {k}: empty or whitespace only")
    return findings


def check_json_duplicate_keys(text: str) -> list[str]:
    """The standard JSON parser silently keeps the last value of a repeated key."""
    findings = []

    def hook(pairs):
        ident = next((v for k, v in pairs if k == "id"), None)
        for key, n in Counter(k for k, _ in pairs).items():
            if n > 1:
                findings.append(f"object with id {show(str(ident))}: key `{show(key)}` appears {n} times")
        return dict(pairs)

    json.loads(text, object_pairs_hook=hook)
    return findings


def check_id_duplicates(articles) -> list[str]:
    counts = Counter(a["id"] for _, a in articles if isinstance(a.get("id"), str))
    return [f"`{show(i)}` used by {n} records" for i, n in counts.items() if n > 1]


def id_shape(ident: str) -> str:
    return re.sub(r"[0-9]", "9", re.sub(r"[A-Za-z]", "A", ident))


def check_id_format(articles) -> list[str]:
    """Ids whose shape (letters -> A, digits -> 9) differs from the most common one."""
    ids = [a["id"] for _, a in articles if isinstance(a.get("id"), str)]
    shapes = Counter(id_shape(i) for i in ids)
    if not shapes:
        return []
    usual = shapes.most_common(1)[0][0]
    return [f"`{show(i)}` has shape `{show(id_shape(i))}`, usual is `{usual}`" for i in ids if id_shape(i) != usual]


def check_id_gaps(articles) -> list[str]:
    numbers = defaultdict(set)
    for _, a in articles:
        m = re.fullmatch(r"([A-Za-z]*)([0-9]+)", a["id"]) if isinstance(a.get("id"), str) else None
        if m:
            numbers[m[1]].add(int(m[2]))
    findings = []
    for prefix, nums in sorted(numbers.items()):
        missing = sorted(set(range(min(nums), max(nums) + 1)) - nums)
        if missing:
            findings.append(f"prefix `{prefix}`: numbers {min(nums)} to {max(nums)}, missing {missing}")
    return findings


# --- news.json: dates -------------------------------------------------------------

DATE_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}")


def parse_date(value) -> datetime | None:
    """Naive local datetime, or None unless the value is exactly YYYY-MM-DDTHH:MM and valid."""
    if not isinstance(value, str) or not DATE_PATTERN.fullmatch(value):
        return None
    try:
        return datetime.strptime(value, config.DATE_FORMAT)
    except ValueError:
        return None


def article_dates(articles) -> list[tuple[str, datetime]]:
    return [(rid, d) for rid, a in articles if (d := parse_date(a.get("date")))]


def check_date_format(articles) -> list[str]:
    return [
        f"{rid}: `{show(a['date'])}`"
        for rid, a in articles
        if isinstance(a.get("date"), str) and parse_date(a["date"]) is None
    ]


def check_future_dates(articles) -> list[str]:
    return [
        f"{rid}: {d:%Y-%m-%dT%H:%M} is after as_of {config.AS_OF:%Y-%m-%dT%H:%M}"
        for rid, d in article_dates(articles)
        if d.replace(tzinfo=config.TIMEZONE) > config.AS_OF
    ]


def local_time_issue(naive: datetime) -> str | None:
    """Daylight saving: some local times do not exist, others occur twice."""
    aware = naive.replace(tzinfo=config.TIMEZONE)
    if aware.astimezone(timezone.utc).astimezone(config.TIMEZONE).replace(tzinfo=None) != naive:
        return "does not exist in New York time (clocks jump forward)"
    if aware.utcoffset() != naive.replace(tzinfo=config.TIMEZONE, fold=1).utcoffset():
        return "is ambiguous in New York time (clocks fall back)"
    return None


def check_local_times(articles) -> list[str]:
    return [f"{rid}: {d:%Y-%m-%dT%H:%M} {issue}" for rid, d in article_dates(articles) if (issue := local_time_issue(d))]


def overview_dates(articles) -> list[str]:
    dates = sorted(d for _, d in article_dates(articles))
    if not dates:
        return []
    zones = Counter(d.replace(tzinfo=config.TIMEZONE).tzname() for d in dates)
    return [
        f"{len(dates)} valid dates, from {dates[0]:%Y-%m-%dT%H:%M} to {dates[-1]:%Y-%m-%dT%H:%M}",
        "time zone abbreviations: " + ", ".join(f"{n} {z}" for z, n in sorted(zones.items())),
    ]


# --- Text checks (article headline/body, sp500.csv cells) -------------------------------


def find_chars(texts, wanted) -> list[str]:
    """One finding per text containing wanted characters: which ones, how many, first context."""
    findings = []
    for where, text in texts:
        hits = [(i, c) for i, c in enumerate(text) if wanted(c)]
        if hits:
            counts = ", ".join(f"{n} x {char_label(c)}" for c, n in sorted(Counter(c for _, c in hits).items()))
            findings.append(f"{where}: {counts}; first at `{snippet(text, hits[0][0])}`")
    return findings


def check_invisible(texts) -> list[str]:
    """Format and control characters (zero-width spaces, BOM, soft hyphen, bidi controls...)."""
    return find_chars(texts, lambda c: unicodedata.category(c) in {"Cc", "Cf", "Co", "Cs", "Cn"} and c not in "\n\r\t")


def check_unusual_spaces(texts) -> list[str]:
    return find_chars(texts, lambda c: unicodedata.category(c) in {"Zs", "Zl", "Zp"} and c != " ")


def check_compatibility_chars(texts) -> list[str]:
    """Characters that NFKC normalisation would replace (fullwidth letters, ligatures, ellipsis...)."""
    return find_chars(
        texts, lambda c: unicodedata.normalize("NFKC", c) != c and unicodedata.category(c) not in {"Zs", "Zl", "Zp"}
    )


def check_not_nfc(texts) -> list[str]:
    findings = []
    for where, text in texts:
        if unicodedata.normalize("NFC", text) != text:
            pos = next((i for i, c in enumerate(text) if unicodedata.combining(c)), 0)
            findings.append(f"{where}: not in NFC form, e.g. `{snippet(text, pos)}`")
    return findings


def script(c: str) -> str:
    return unicodedata.name(c, "UNKNOWN").split()[0]


def check_homoglyphs(texts) -> list[str]:
    """Words containing non-Latin letters; mixed Latin/non-Latin words are likely look-alikes."""
    findings = []
    for where, text in texts:
        words = Counter(w for w in re.findall(r"\w+", text) if any(c.isalpha() and script(c) != "LATIN" for c in w))
        for word, n in words.items():
            kind = "mixed-script word" if any(script(c) == "LATIN" for c in word) else "non-Latin word"
            chars = ", ".join(char_label(c) for c in sorted({c for c in word if c.isalpha() and script(c) != "LATIN"}))
            findings.append(f"{where}: {n} x {kind} `{show(word)}` ({chars})")
    return findings


PLACEHOLDERS = {"none", "null", "nan", "n/a", "unknown", "-", "?"}


def check_placeholders(texts) -> list[str]:
    """Values that stand for a missing value instead of being empty."""
    return [f"{where}: `{show(text)}`" for where, text in texts if text.strip().casefold() in PLACEHOLDERS]


WHITESPACE_NOISE = {
    "repeated spaces": re.compile(r"  +"),
    "tab": re.compile(r"\t"),
    "carriage return": re.compile(r"\r"),
    "space before line break": re.compile(r" +\n"),
    "3+ line breaks in a row": re.compile(r"\n{3,}"),
}


def check_whitespace(texts, single_line: bool) -> list[str]:
    findings = []
    for where, text in texts:
        issues = ["leading/trailing whitespace"] if text != text.strip() else []
        issues += [f"{len(p.findall(text))} x {name}" for name, p in WHITESPACE_NOISE.items() if p.search(text)]
        if single_line and "\n" in text:
            issues.append("line break")
        if issues:
            findings.append(f"{where}: " + ", ".join(issues))
    return findings


MARKUP = re.compile(r"</?[A-Za-z][A-Za-z0-9]*[^<>]{0,100}>|&(?:[A-Za-z]{2,8}|#[0-9]{1,7}|#x[0-9A-Fa-f]{1,6});")


def check_markup(texts) -> list[str]:
    """HTML tags or entities in text that should be plain."""
    findings = []
    for where, text in texts:
        found = sorted(set(MARKUP.findall(text)))
        if found:
            findings.append(f"{where}: " + ", ".join(f"`{show(m)}`" for m in found))
    return findings


def check_body_ending(articles) -> list[str]:
    """Bodies not ending with sentence punctuation may be truncated."""
    findings = []
    for rid, a in articles:
        body = a.get("body")
        if isinstance(body, str) and body.strip() and not re.search(r"[.!?\"')\]”’]$", body.rstrip()):
            findings.append(f"{rid}: ends with `{show(body.rstrip()[-40:])}`")
    return findings


def char_inventory(texts) -> list[str]:
    """Every non-ASCII character, with its count and where it appears."""
    counts, where_seen = Counter(), defaultdict(list)
    for where, text in texts:
        record = where.rsplit(" ", 1)[0]
        for c in text:
            if ord(c) > 127:
                counts[c] += 1
                if record not in where_seen[c]:
                    where_seen[c].append(record)
    findings = []
    for c, n in sorted(counts.items()):
        seen = where_seen[c]
        places = ", ".join(seen[:6]) + (f" and {len(seen) - 6} more" if len(seen) > 6 else "")
        findings.append(f"{char_label(c)} [{unicodedata.category(c)}]: {n} in {places}")
    return findings


# --- news.json: duplicates and lengths ------------------------------------------------


def check_exact_duplicates(articles) -> list[str]:
    """Articles with the same headline and/or body once case, spaces and invisible characters are ignored."""
    findings, reported = [], set()
    for fields in (("headline", "body"), ("headline",), ("body",)):
        groups = defaultdict(list)
        for rid, a in articles:
            if all(isinstance(a.get(f), str) for f in fields):
                groups[tuple(comparable(a[f]) for f in fields)].append((rid, a))
        for group in groups.values():
            ids = frozenset(rid for rid, _ in group)
            if len(group) < 2 or ids in reported:
                continue
            reported.add(ids)
            raw_same = len({tuple(a[f] for f in fields) for _, a in group}) == 1
            how = "identical" if raw_same else "identical after normalising case, spaces and invisible characters"
            members = ", ".join(f"{rid} ({show(str(a.get('date')))})" for rid, a in group)
            findings.append(f"same {' + '.join(fields)}, {how}: {members}")
    return findings


def shingles(text: str) -> set:
    """Sequences of 5 consecutive words of an already comparable text."""
    words = re.findall(r"\w+", text)
    return {tuple(words[i : i + SHINGLE_WORDS]) for i in range(max(1, len(words) - SHINGLE_WORDS + 1))}


def body_similarities(articles) -> list[tuple[float, str, str, dict, dict]]:
    """Jaccard similarity of 5-word shingles for every pair of bodies that are not exact duplicates."""
    bodies = [(rid, a, comparable(a["body"])) for rid, a in articles if isinstance(a.get("body"), str)]
    bodies = [(rid, a, text, shingles(text)) for rid, a, text in bodies]
    pairs = []
    for (r1, a1, t1, s1), (r2, a2, t2, s2) in combinations(bodies, 2):
        if t1 != t2:
            pairs.append((len(s1 & s2) / len(s1 | s2), r1, r2, a1, a2))
    return sorted(pairs, key=lambda p: (-p[0], p[1], p[2]))


def check_near_duplicates(articles) -> list[str]:
    return [
        f"{r1} ~ {r2}: similarity {score:.2f}; dates {show(str(a1.get('date')))} / {show(str(a2.get('date')))}; "
        f"headlines `{show(str(a1.get('headline')))[:70]}` / `{show(str(a2.get('headline')))[:70]}`"
        for score, r1, r2, a1, a2 in body_similarities(articles)
        if score >= NEAR_DUPLICATE_MIN
    ]


def overview_news(news, articles) -> list[str]:
    lines = [f"{len(news) if isinstance(news, list) else 0} records, {len(articles)} of them JSON objects"]
    for field in ("headline", "body"):
        sized = sorted((len(a[field]), rid) for rid, a in articles if isinstance(a.get(field), str))
        if sized:
            lengths = [n for n, _ in sized]
            shortest = ", ".join(f"{rid} ({n})" for n, rid in sized[:3])
            longest = ", ".join(f"{rid} ({n})" for n, rid in sized[-3:])
            lines.append(
                f"{field} length: min {lengths[0]}, median {statistics.median(lengths):g}, max {lengths[-1]} "
                f"characters; shortest {shortest}; longest {longest}"
            )
    below = [p[0] for p in body_similarities(articles) if p[0] < NEAR_DUPLICATE_MIN]
    if below:
        lines.append(f"body similarity: highest score below {NEAR_DUPLICATE_MIN} is {max(below):.2f}")
    return lines


# --- sp500.csv ---------------------------------------------------------------------


def check_sp500_header(header) -> list[str]:
    if tuple(header) == config.SP500_COLUMNS:
        return []
    return [f"header is {[show(h) for h in header]}, expected {list(config.SP500_COLUMNS)}"]


def check_sp500_cells(header, rows) -> list[str]:
    findings = []
    for n, row in enumerate(rows, start=2):
        if len(row) != len(header):
            findings.append(f"row {n}: {len(row)} cells instead of {len(header)}: `{show(','.join(row))[:80]}`")
        findings += [f"row {n} {show(col)}: empty" for col, cell in zip(header, row) if not cell.strip()]
    return findings


def check_symbol_duplicates(records) -> list[str]:
    rows = defaultdict(list)
    for n, r in records:
        if r.get("symbol"):
            rows[r["symbol"].strip()].append(n)
    return [f"`{show(s)}` on rows {ns}" for s, ns in rows.items() if len(ns) > 1]


def check_symbol_format(records) -> list[str]:
    """US ticker shape: 1-5 capital letters, optionally a dot and a share-class letter (BRK.B)."""
    return [
        f"row {n}: `{show(r['symbol'])}`"
        for n, r in records
        if "symbol" in r and not re.fullmatch(r"[A-Z]{1,5}(\.[A-Z])?", r["symbol"])
    ]


def check_security_duplicates(records) -> list[str]:
    rows = defaultdict(list)
    for n, r in records:
        if r.get("security"):
            rows[comparable(r["security"])].append((n, r))
    return [
        "same name: " + ", ".join(f"row {n} `{show(r['security'])}` ({show(r.get('symbol', ''))})" for n, r in group)
        for group in rows.values()
        if len(group) > 1
    ]


CLASS_MARK = re.compile(r"\s*\(?\bClass [A-Z]\b\)?", re.IGNORECASE)


def overview_share_classes(records) -> list[str]:
    """Dual-class companies: names equal once a 'Class X' marker is removed, in file order."""
    groups = defaultdict(list)
    for n, r in records:
        if r.get("security"):
            groups[comparable(CLASS_MARK.sub("", r["security"]))].append((n, r))
    lines = [
        "same company: " + ", ".join(f"{show(r.get('symbol', ''))} (row {n}, `{show(r['security'])}`)" for n, r in g)
        for g in groups.values()
        if len(g) > 1
    ]
    dotted = [show(r["symbol"]) for _, r in records if "." in r.get("symbol", "")]
    if dotted:
        lines.append(f"symbols with a share-class suffix: {', '.join(dotted)}")
    return lines


def check_date_added(records) -> list[str]:
    findings = []
    for n, r in records:
        value = r.get("date_added")
        if value is None:
            continue
        try:
            if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
                raise ValueError
            added = datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            findings.append(f"row {n}: `{show(value)}` is not a YYYY-MM-DD date")
            continue
        if added > config.AS_OF.date():
            findings.append(f"row {n} ({show(r.get('symbol', ''))}): added {added} after as_of")
    return findings


def check_value_variants(records, column: str) -> list[str]:
    """Values of one column that differ only by case, spaces or invisible characters."""
    groups = defaultdict(set)
    for _, r in records:
        if r.get(column):
            groups[comparable(r[column])].add(r[column])
    return [", ".join(f"`{show(v)}`" for v in sorted(vs)) for vs in groups.values() if len(vs) > 1]


def check_headquarters_format(records) -> list[str]:
    """Expected shape 'City, State' or 'City, Country'."""
    return [
        f"row {n}: `{show(r['headquarters'])}`"
        for n, r in records
        if r.get("headquarters") and not re.fullmatch(r"[^,]+, [^,]+", r["headquarters"])
    ]


LEGAL_FORM = re.compile(r"\b(Inc|Corp|Corporation|Co|Company|Companies|plc|Ltd|Limited|Group|Holdings|N\.V|S\.A|AG|SE)\b\.?")


def overview_sp500(header, rows, records) -> list[str]:
    lines = [f"{len(rows)} data rows, {len({r.get('symbol') for _, r in records})} distinct symbols"]
    added = sorted(r["date_added"] for _, r in records if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", r.get("date_added", "")))
    if added:
        lines.append(f"date_added from {added[0]} to {added[-1]}")
    sectors = Counter(r.get("gics_sector") for _, r in records)
    lines.append("sectors: " + ", ".join(f"{show(str(s))} ({n})" for s, n in sorted(sectors.items(), key=str)))
    names = [r["security"] for _, r in records if r.get("security")]
    for label, test in (
        ("a legal-form word (Inc., Corp., plc...)", LEGAL_FORM.search),
        ("'&'", lambda s: "&" in s),
        ("a leading 'The'", lambda s: s.startswith("The ")),
    ):
        hits = [n for n in names if test(n)]
        lines.append(f"{len(hits)} names contain {label}" + (f", e.g. `{show(hits[0])}`" if hits else ""))
    other = [n for n in names if "(" in n and not CLASS_MARK.search(n)]
    lines.append(f"{len(other)} names with a parenthesised part other than a share class: " + ", ".join(f"`{show(n)}`" for n in other))
    return lines


# --- Audit and report -----------------------------------------------------------------


def text_checks(prefix: str, texts, single_line: bool) -> list[tuple[str, str, list[str]]]:
    return [
        (f"{prefix}: homoglyphs (non-Latin letters)", "warning", check_homoglyphs(texts)),
        (f"{prefix}: invisible and control characters", "warning", check_invisible(texts)),
        (f"{prefix}: unusual spaces", "warning", check_unusual_spaces(texts)),
        (f"{prefix}: not in NFC form", "warning", check_not_nfc(texts)),
        (f"{prefix}: characters changed by NFKC", "info", check_compatibility_chars(texts)),
        (f"{prefix}: whitespace noise", "warning", check_whitespace(texts, single_line)),
        (f"{prefix}: HTML tags or entities", "warning", check_markup(texts)),
        (f"{prefix}: mojibake", "warning", check_mojibake(texts)),
        (f"{prefix}: placeholder values", "warning", check_placeholders(texts)),
    ]


def audit(news_path: Path, sp500_path: Path) -> list[tuple[str, str, list[str]]]:
    """(title, severity, findings) for every check, in report order."""
    sections = [("news.json: file encoding and line endings", "warning", check_file_bytes(Path(news_path).read_bytes()))]
    try:
        news = load.load_news(news_path)
        duplicate_keys = check_json_duplicate_keys(load.read_text(news_path))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        sections.append(("news.json: parsing", "error", [str(e)]))
        news, duplicate_keys = None, []
    articles = news_records(news)
    headlines, bodies = news_texts(articles, "headline"), news_texts(articles, "body")
    sections += [
        ("news.json: structure", "error", check_news_structure(news) if news is not None else []),
        ("news.json: repeated JSON keys", "error", duplicate_keys),
        ("news.json: duplicate ids", "error", check_id_duplicates(articles)),
        ("news.json: id format", "warning", check_id_format(articles)),
        ("news.json: gaps in id numbering", "info", check_id_gaps(articles)),
        ("news.json: date format", "error", check_date_format(articles)),
        ("news.json: dates after as_of", "error", check_future_dates(articles)),
        ("news.json: non-existent or ambiguous local times", "warning", check_local_times(articles)),
        *text_checks("news.json headline", headlines, single_line=True),
        *text_checks("news.json body", bodies, single_line=False),
        ("news.json: bodies not ending with punctuation", "warning", check_body_ending(articles)),
        ("news.json: exact duplicates", "warning", check_exact_duplicates(articles)),
        (f"news.json: near-duplicate bodies (similarity >= {NEAR_DUPLICATE_MIN})", "warning", check_near_duplicates(articles)),
        ("news.json: overview", "info", overview_news(news, articles) + overview_dates(articles)),
        ("news.json: non-ASCII characters", "info", char_inventory(headlines + bodies)),
    ]

    sections.append(("sp500.csv: file encoding and line endings", "warning", check_file_bytes(Path(sp500_path).read_bytes())))
    try:
        header, rows = load.load_sp500(sp500_path)
    except UnicodeDecodeError as e:
        sections.append(("sp500.csv: parsing", "error", [str(e)]))
        header, rows = [], []
    records, cells = sp500_records(header, rows), sp500_texts(header, rows)
    sections += [
        ("sp500.csv: header", "error", check_sp500_header(header)),
        ("sp500.csv: cell count and empty cells", "error", check_sp500_cells(header, rows)),
        *text_checks("sp500.csv", cells, single_line=True),
        ("sp500.csv: duplicate symbols", "error", check_symbol_duplicates(records)),
        ("sp500.csv: symbol format", "warning", check_symbol_format(records)),
        ("sp500.csv: duplicate company names", "warning", check_security_duplicates(records)),
        ("sp500.csv: date_added", "warning", check_date_added(records)),
        ("sp500.csv: gics_sector variants", "warning", check_value_variants(records, "gics_sector")),
        ("sp500.csv: headquarters format", "info", check_headquarters_format(records)),
        ("sp500.csv: share classes", "info", overview_share_classes(records)),
        ("sp500.csv: overview", "info", overview_sp500(header, rows, records)),
        ("sp500.csv: non-ASCII characters", "info", char_inventory(cells)),
    ]
    return sections


def render(sections, news_path: Path, sp500_path: Path) -> str:
    lines = [
        "# Data audit report",
        "",
        f"Generated by `python -m sp500_sentiment.audit --news {Path(news_path).as_posix()} "
        f"--sp500 {Path(sp500_path).as_posix()}`. Do not edit by hand.",
        "",
    ]
    for path in (news_path, sp500_path):
        lines.append(f"- `{Path(path).as_posix()}` sha256 `{hashlib.sha256(Path(path).read_bytes()).hexdigest()}`")
    lines += [
        "",
        "Severity: **error** breaks parsing or the schema; **warning** needs a cleaning decision; "
        "**info** is context. Characters outside printable ASCII are shown as escapes (e.g. `\\u200b`). "
        "Row numbers in sp500.csv count the header as row 1.",
        "",
        "## Summary",
        "",
        "| Check | Severity | Count |",
        "|---|---|---|",
    ]
    lines += [f"| {title} | {severity} | {len(findings)} |" for title, severity, findings in sections]
    for title, severity, findings in sections:
        if findings:
            lines += ["", f"## {title} ({severity}, {len(findings)})", ""]
            lines += [f"- {f}" for f in findings[:MAX_LINES]]
            if len(findings) > MAX_LINES:
                lines.append(f"- ... and {len(findings) - MAX_LINES} more")
    return "\n".join(lines) + "\n"


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Read-only audit of news.json and sp500.csv.")
    parser.add_argument("--news", type=Path, default=config.NEWS_PATH)
    parser.add_argument("--sp500", type=Path, default=config.SP500_PATH)
    parser.add_argument("--out", type=Path, help="also write the Markdown report to this file")
    args = parser.parse_args(argv)
    report = render(audit(args.news, args.sp500), args.news, args.sp500)
    print(report, end="")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
