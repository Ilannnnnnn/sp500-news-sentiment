# S&P 500 entity-level news sentiment

Command-line pipeline: reads news articles (`data/news.json`) and the S&P 500 constituents
(`data/sp500.csv`), identifies which S&P 500 companies each article concerns, labels the
implication for each company (`positive` / `neutral` / `negative`), and writes
`entities.csv` and `scores.csv`.

**Status:** Step 0 (project setup). The pipeline itself is not implemented yet; the
end-to-end run command will be added here when it exists. See
[`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) for the roadmap and decision log.

## Requirements

- Python 3.11 or newer.
- Recommended: [uv](https://docs.astral.sh/uv/), which installs the exact versions pinned in `uv.lock`.
- Fallback: plain `pip`, using `requirements.txt` (generated from `uv.lock`, same pinned versions).

## Setup

With uv (recommended):

```bash
uv sync
```

With pip (fallback):

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Run the tests

```bash
uv run pytest          # with uv
python -m pytest       # with pip, inside the activated virtual environment
```

Tests never call the network; LLM responses are faked.

## Repository layout

```
sp500_sentiment/        Python package (run from the repository root)
tests/                  pytest tests
data/                   raw inputs, never modified by the pipeline
output/                 generated files (ignored during development)
CLAUDE.md               rules for the coding agent
IMPLEMENTATION_PLAN.md  roadmap and decision log
```
