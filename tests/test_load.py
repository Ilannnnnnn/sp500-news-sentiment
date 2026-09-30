import codecs

from sp500_sentiment import load


def test_load_news_parses_json_and_tolerates_bom(tmp_path):
    path = tmp_path / "news.json"
    path.write_bytes(codecs.BOM_UTF8 + '[{"id": "N1", "headline": "Café"}]'.encode("utf-8"))
    assert load.load_news(path) == [{"id": "N1", "headline": "Café"}]


def test_load_sp500_keeps_cells_raw(tmp_path):
    path = tmp_path / "sp500.csv"
    path.write_text("symbol,security\nAAPL ,Apple​ Inc. \n", encoding="utf-8")
    assert load.load_sp500(path) == (["symbol", "security"], [["AAPL ", "Apple​ Inc. "]])


def test_load_sp500_quoted_comma(tmp_path):
    path = tmp_path / "sp500.csv"
    path.write_text('symbol,headquarters\nMMM,"Saint Paul, Minnesota"\n', encoding="utf-8")
    assert load.load_sp500(path) == (["symbol", "headquarters"], [["MMM", "Saint Paul, Minnesota"]])


def test_load_sp500_empty_file(tmp_path):
    path = tmp_path / "sp500.csv"
    path.write_text("", encoding="utf-8")
    assert load.load_sp500(path) == ([], [])
