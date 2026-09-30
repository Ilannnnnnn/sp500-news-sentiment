import codecs
import json

import pytest

from sp500_sentiment import audit

LONG_BODY = " ".join(f"word{i}" for i in range(60)) + "."


def article(ident="N001", date="2026-09-01T10:00", headline="Apple wins contract", body="Apple won a contract."):
    return {"id": ident, "date": date, "headline": headline, "body": body}


def records(*articles):
    return audit.news_records(list(articles))


def texts(*values):
    return [(f"t{i}", v) for i, v in enumerate(values)]


def test_show_escapes_everything_outside_printable_ascii():
    assert audit.show("A​B\nа`") == "A\\u200bB\\n\\u0430\\x60"


# --- File level -------------------------------------------------------------------


@pytest.mark.parametrize(
    "data, expected",
    [
        (codecs.BOM_UTF8 + b"[]\n", "byte order mark"),
        (b"[\xff]\n", "invalid UTF-8"),
        (b"a\r\nb\nc\n", "mixed line endings"),
        (b"a\rb", "mixed line endings"),
    ],
)
def test_file_bytes_flagged(data, expected):
    assert expected in " ".join(audit.check_file_bytes(data))


def test_file_bytes_clean():
    assert audit.check_file_bytes(b"[1,\n2]\n") == []
    assert audit.check_file_bytes(b"a\r\nb\r\n") == []


def test_mojibake():
    assert audit.check_mojibake(texts("donâ€™t"))  # "donâ€™t"
    assert audit.check_mojibake(texts("café ’quoted’ — а")) == []


# --- news.json structure and ids ---------------------------------------------------------


@pytest.mark.parametrize(
    "news, expected",
    [
        ({"id": "N001"}, "expected a list"),
        (["text"], "expected an object"),
        ([{"id": "N001", "date": "2026-09-01T10:00", "headline": "h"}], "missing keys ['body']"),
        ([{**article(), "source": "x"}], "unexpected keys ['source']"),
        ([{**article(), "body": None}], "NoneType value"),
        ([{**article(), "headline": 42}], "int value"),
        ([{**article(), "body": "  \n "}], "empty or whitespace only"),
    ],
)
def test_news_structure_flagged(news, expected):
    assert expected in " ".join(audit.check_news_structure(news))


def test_news_structure_clean():
    assert audit.check_news_structure([article()]) == []


def test_json_duplicate_keys():
    text = '[{"id": "N001", "body": "a", "body": "b"}, {"id": "N002", "body": "c"}]'
    assert audit.check_json_duplicate_keys(text) == ["object with id N001: key `body` appears 2 times"]
    assert audit.check_json_duplicate_keys(json.dumps([article()])) == []


def test_id_duplicates_format_and_gaps():
    arts = records(article("N001"), article("N001"), article("N0​03"), article(" N004"), article("N006"))
    assert audit.check_id_duplicates(arts) == ["`N001` used by 2 records"]
    assert len(audit.check_id_format(arts)) == 2
    assert audit.check_id_gaps(arts) == ["prefix `N`: numbers 1 to 6, missing [2, 3, 4, 5]"]
    clean = records(article("N001"), article("N002"))
    assert (audit.check_id_duplicates(clean), audit.check_id_format(clean), audit.check_id_gaps(clean)) == ([], [], [])


# --- news.json dates ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    ["2026-08-25 06:53", "2026-8-25T06:53", "2026-08-25T06:53:00", "2026-08-25T06:53Z", "2026-02-30T10:00", "25/08/2026", ""],
)
def test_date_format_flagged(value):
    assert audit.check_date_format(records(article(date=value)))


def test_date_format_clean():
    assert audit.check_date_format(records(article(date="2026-08-25T06:53"))) == []


def test_future_dates():
    assert audit.check_future_dates(records(article(date="2026-09-29T00:01")))
    assert audit.check_future_dates(records(article(date="2026-09-29T00:00"))) == []


@pytest.mark.parametrize(
    "value, expected",
    [("2026-03-08T02:30", "does not exist"), ("2026-11-01T01:30", "ambiguous"), ("2026-09-28T16:20", None)],
)
def test_local_times(value, expected):
    findings = audit.check_local_times(records(article(date=value)))
    assert (expected in findings[0]) if expected else findings == []


def test_overview_dates_reports_range_and_zone():
    arts = records(article("N001", date="2026-08-25T06:53"), article("N002", date="2026-09-28T16:20"))
    assert audit.overview_dates(arts) == [
        "2 valid dates, from 2026-08-25T06:53 to 2026-09-28T16:20",
        "time zone abbreviations: 2 EDT",
    ]


# --- Text checks -------------------------------------------------------------------------


def test_homoglyphs():
    findings = audit.check_homoglyphs(texts("Аpple beats estimates", "сок"))
    assert "mixed-script word `\\u0410pple`" in findings[0] and "CYRILLIC CAPITAL LETTER A" in findings[0]
    assert "non-Latin word" in findings[1]
    assert audit.check_homoglyphs(texts("Nestlé and Apple", "3M 10% AT&T")) == []


def test_homoglyphs_counted_once_per_word_and_text():
    findings = audit.check_homoglyphs(texts("Тesla and Тesla again, ТSLA"))
    assert [f.split(" (")[0] for f in findings] == ["t0: 2 x mixed-script word `\\u0422esla`", "t0: 1 x mixed-script word `\\u0422SLA`"]


@pytest.mark.parametrize("value", ["none", " N/A ", "NULL", "nan", "-", "Unknown"])
def test_placeholders_flagged(value):
    assert audit.check_placeholders(texts(value))


def test_placeholders_clean():
    assert audit.check_placeholders(texts("Nonestop Inc.", "Omaha, Nebraska", "")) == []


@pytest.mark.parametrize("char", ["​", "﻿", "­", "‮", "\x07"])
def test_invisible_flagged(char):
    assert audit.check_invisible(texts(f"Ap{char}ple"))


def test_invisible_clean():
    assert audit.check_invisible(texts("line\n\tnext\r\n")) == []


def test_unusual_spaces():
    assert "NO-BREAK SPACE" in audit.check_unusual_spaces(texts("10 %"))[0]
    assert audit.check_unusual_spaces(texts("plain text")) == []


def test_normalisation_checks():
    assert audit.check_not_nfc(texts("Nestlé"))
    assert audit.check_not_nfc(texts("Nestlé")) == []
    assert "FULLWIDTH" in audit.check_compatibility_chars(texts("Ａpple"))[0]
    assert audit.check_compatibility_chars(texts("Apple  ")) == []


@pytest.mark.parametrize(
    "value, expected",
    [
        (" Apple", "leading/trailing whitespace"),
        ("Apple  wins", "repeated spaces"),
        ("Apple\twins", "tab"),
        ("Apple\r\nwins", "carriage return"),
        ("Apple \nwins", "space before line break"),
        ("Apple\n\n\nwins", "3+ line breaks"),
    ],
)
def test_whitespace_flagged(value, expected):
    assert expected in audit.check_whitespace(texts(value), single_line=False)[0]


def test_whitespace_single_line_and_clean():
    assert "line break" in audit.check_whitespace(texts("Apple\nwins"), single_line=True)[0]
    assert audit.check_whitespace(texts("Apple wins.\n\nNext paragraph."), single_line=False) == []


def test_markup():
    assert audit.check_markup(texts("<p>Apple</p> &amp; Co &#8217;"))
    assert audit.check_markup(texts("AT&T and P&G; revenue < 5% > 3%")) == []


def test_body_ending():
    arts = records(article("N001", body="Shares rose 5% after the"), article("N002", body="Shares rose.\n"))
    assert audit.check_body_ending(arts) == ["N001: ends with `Shares rose 5% after the`"]


def test_char_inventory_lists_each_character_with_records():
    findings = audit.char_inventory([("N001 body", "a​b​"), ("N002 headline", "​")])
    assert findings == ["U+200B ZERO WIDTH SPACE [Cf]: 3 in N001, N002"]


# --- Duplicates --------------------------------------------------------------------------


def test_exact_duplicates_after_normalisation():
    arts = records(article("N001", body="Apple won."), article("N002", body="apple  won.​"), article("N003", headline="Other"))
    findings = audit.check_exact_duplicates(arts)
    assert findings == [
        "same headline + body, identical after normalising case, spaces and invisible characters: "
        "N001 (2026-09-01T10:00), N002 (2026-09-01T10:00)"
    ]


def test_exact_duplicates_clean():
    assert audit.check_exact_duplicates(records(article("N001", body="A."), article("N002", headline="B", body="B."))) == []


def test_near_duplicates():
    edited = LONG_BODY.replace("word30", "changed")
    arts = records(article("N001", body=LONG_BODY), article("N002", body=edited), article("N003", body="Unrelated text here."))
    findings = audit.check_near_duplicates(arts)
    assert len(findings) == 1 and findings[0].startswith("N001 ~ N002: similarity 0.8")


# --- sp500.csv ------------------------------------------------------------------------------

HEADER = ["symbol", "security", "gics_sector", "headquarters", "date_added"]


def sp500(*rows):
    return audit.sp500_records(HEADER, [list(r) for r in rows])


def test_sp500_header_and_cells():
    assert audit.check_sp500_header(HEADER) == []
    assert audit.check_sp500_header(["Symbol", *HEADER[1:]])
    findings = audit.check_sp500_cells(HEADER, [["MMM", "3M", "Industrials"], ["AOS", "", "Industrials", "Milwaukee, Wisconsin", "2017-07-26"]])
    assert findings == ["row 2: 3 cells instead of 5: `MMM,3M,Industrials`", "row 3 security: empty"]


def test_symbols():
    rows = sp500(
        ("BRK.B", "Berkshire Hathaway", "Financials", "Omaha, Nebraska", "2010-02-16"),
        ("BF-B", "Brown-Forman", "Consumer Staples", "Louisville, Kentucky", "1982-10-31"),
        ("aapl", "Apple Inc.", "Information Technology", "Cupertino, California", "1982-11-30"),
        ("BRK.B", "Berkshire Hathaway", "Financials", "Omaha, Nebraska", "2010-02-16"),
    )
    assert audit.check_symbol_duplicates(rows) == ["`BRK.B` on rows [2, 5]"]
    assert audit.check_symbol_format(rows) == ["row 3: `BF-B`", "row 4: `aapl`"]
    assert len(audit.check_security_duplicates(rows)) == 1


def test_share_classes_grouped_in_file_order():
    rows = sp500(
        ("GOOGL", "Alphabet Inc. (Class A)", "Communication Services", "Mountain View, California", "2014-04-03"),
        ("MMM", "3M", "Industrials", "Saint Paul, Minnesota", "1957-03-04"),
        ("GOOG", "Alphabet Inc. (Class C)", "Communication Services", "Mountain View, California", "2006-04-03"),
    )
    assert audit.overview_share_classes(rows) == [
        "same company: GOOGL (row 2, `Alphabet Inc. (Class A)`), GOOG (row 4, `Alphabet Inc. (Class C)`)"
    ]


def test_date_added():
    rows = sp500(
        ("A", "A Co", "Health Care", "Santa Clara, California", "2000-06-05"),
        ("B", "B Co", "Health Care", "Santa Clara, California", "2026-09-30"),
        ("C", "C Co", "Health Care", "Santa Clara, California", "05/06/2000"),
    )
    assert audit.check_date_added(rows) == ["row 3 (B): added 2026-09-30 after as_of", "row 4: `05/06/2000` is not a YYYY-MM-DD date"]


def test_value_variants_and_headquarters():
    rows = sp500(
        ("A", "A Co", "Health Care", "Santa Clara, California", "2000-06-05"),
        ("B", "B Co", "health care ", "Dublin", "2000-06-05"),
    )
    assert audit.check_value_variants(rows, "gics_sector") == ["`Health Care`, `health care `"]
    assert audit.check_headquarters_format(rows) == ["row 3: `Dublin`"]


# --- End to end ------------------------------------------------------------------------------


def write_inputs(tmp_path):
    news = tmp_path / "news.json"
    news.write_text(json.dumps([article("N001"), article("N002", headline="Аpple", body="Ap​ple.")]), encoding="utf-8")
    csv = tmp_path / "sp500.csv"
    csv.write_text(",".join(HEADER) + "\nAAPL,Apple Inc.,Information Technology,\"Cupertino, California\",1982-11-30\n", encoding="utf-8")
    return news, csv


def test_main_is_read_only_deterministic_and_writes_report(tmp_path, capsys):
    news, csv = write_inputs(tmp_path)
    before = (news.read_bytes(), csv.read_bytes())
    out = tmp_path / "reports" / "audit.md"
    audit.main(["--news", str(news), "--sp500", str(csv), "--out", str(out)])
    first = out.read_text(encoding="utf-8")
    audit.main(["--news", str(news), "--sp500", str(csv), "--out", str(out)])
    assert (news.read_bytes(), csv.read_bytes()) == before
    assert out.read_text(encoding="utf-8") == first
    assert "news.json headline: homoglyphs (non-Latin letters) | warning | 1 |" in first
    assert "news.json body: invisible and control characters | warning | 1 |" in first
    assert first.isascii()
    assert capsys.readouterr().out.startswith("# Data audit report")


def test_unparseable_json_is_reported_not_raised(tmp_path):
    news, csv = write_inputs(tmp_path)
    news.write_text('[{"id": "N001",', encoding="utf-8")
    titles = {title: findings for title, _, findings in audit.audit(news, csv)}
    assert titles["news.json: parsing"]
