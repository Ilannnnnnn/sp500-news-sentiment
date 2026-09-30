# CLAUDE.md — rules for the coding agent

This project is a technical assessment. How the work is planned, delegated and verified
matters as much as the result. These rules come from the project brief and the decisions
recorded in [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md).

## 1. How we work (non-negotiable)

1. **One step at a time.** Never start the next step until the user explicitly approves the current one.
2. **Every key decision goes through the user.** Before implementing anything non-trivial
   (library choice, data structure, normalisation rule, matching strategy, prompt design,
   validation rule, file layout…), present:
   - the decision to make, in one sentence;
   - all reasonable options (typically 2–4), each with pros, cons and impact on
     correctness, robustness, cost and simplicity;
   - a recommendation and why.

   Then stop and wait for the user's choice. Do not pick for the user, even for "obvious" cases.
3. **Plan before code.** At the start of each step, give a short plan (files touched,
   functions, tests) and wait for the go.
4. **Small increments.** Each increment is a small, reviewable diff plus its tests. Show
   what changed and how it was verified (commands run, test output). No large refactors,
   no speculative features.
5. **Keep it simple.** Python, command line only, minimal dependencies, light repository.
   No framework, no over-engineering. The whole project is sized for 4–6 hours: keep each
   piece compact, and if something turns out costly to implement, skip it and say so.
6. **Never invent.** If something is unclear in the spec or the data, say so and ask.
   Never assume silently.
7. **Log decisions.** Every validated decision gets a short entry (context, options,
   choice, reason) in `IMPLEMENTATION_PLAN.md`.
8. **No dataset-specific logic.** Never hard-code behaviour for a specific article id,
   headline or phrase from `news.json`, and never add an alias or rule just to fix one
   article. Every rule must be general and justified independently of this dataset; the
   pipeline must work on equivalent inputs we have not seen.
9. **Tests are not negotiable.** Never modify or delete a test to make it pass. If a test
   fails, fix the code; if you believe the test itself is wrong, stop and tell the user why.
10. **Verify before claiming done.** Before saying a step or increment is finished, run the
    full test suite and show the output. Never report something as working without having
    run it.

## 2. Specification

Python command-line pipeline: **JSON input → CSV output**. The evaluators run it themselves.

**Inputs** (`data/`, never modified):
- `news.json`: list of articles, each with `id`, `date` (local New York time,
  `YYYY-MM-DDTHH:MM`), `headline`, `body` (plain text).
- `sp500.csv`: S&P 500 constituents as of 2026-09-29
  (`symbol, security, gics_sector, headquarters, date_added`). Only these companies count.
  - Dual-class names: use the first listed class (GOOGL, FOXA, NWSA, BRK.B).
  - Brands and subsidiaries map to their parent.

**Task:** for each article, identify which S&P 500 companies it concerns and classify the
implication of the article for each company's value at publication time:
- `positive`: e.g. upgrade with higher price target, contract win, favourable ruling;
- `negative`: e.g. downgrade, guidance cut, lawsuit, recall;
- `neutral`: mentioned without implication (the bank issuing the rating, a media source,
  a customer, a location, a size comparison).

An article can be positive for one company and negative for another. The system must
distinguish companies that are the **subject** of the news from companies merely **mentioned**.

**Outputs:**
- `entities.csv`: columns `id, ticker, label`; one row per (article, company) pair;
  `label ∈ {positive, neutral, negative}`; companies not in `sp500.csv` are never listed.
- `scores.csv`: columns `ticker, value`; one row per ticker appearing in `entities.csv`
  (neutral-only tickers included, with value 0).

**Aggregation (fixed):**
- `weight = 0.5 ^ (days / 7)`, `days = as_of − date` in fractional days,
  `as_of = 2026-09-29 00:00` New York time (`zoneinfo` `America/New_York`).
- `value(ticker) = Σ label × weight` over all articles, with label = +1 / 0 / −1.

## 3. Constraints

- **LLM:** OpenAI `gpt-5.6-terra` only. No other model or provider. Use it only where it
  is useful; document what is done by code vs. by the model, and why.
- **API key:** read from the `OPENAI_API_KEY` environment variable. Never commit it,
  never write it to a file or a log.
- **Every LLM output is validated by code**, never trusted.
- **Determinism:** same results on equivalent inputs.
- **Usage tracking:** record LLM calls and tokens; report the cost per article of a full run.
- **Input is uncleaned production data** from an external provider.
- **No external data** (no news, no prices). **No hand-editing of outputs.**
- **Tests are required.**

## 4. Conventions

- **Layout:** flat package `sp500_sentiment/` at the repository root, run with
  `python -m sp500_sentiment` from the root; tests in `tests/`.
- **Dependencies:** declared in `pyproject.toml`, locked in `uv.lock`. After any
  dependency change, regenerate the pip fallback and commit both files together:
  `uv export --format requirements-txt --no-hashes --output-file requirements.txt`
- **Python:** 3.11 or newer.
- **Tests:** pytest (`uv run pytest`). Tests never call the network; LLM responses are faked.
- **Generated files** (`reports/data_audit.md`, final outputs) are produced by their
  command, never edited by hand; regenerate them when the code or the data changes.
- **Git:**
  - **One pull request per step.** Each step is delivered as one pull request into `main`.
    The user reviews and merges it before the next step starts; the next step starts from
    the updated `main`.
  - Commit the raw inputs in `data/`. Never commit the project brief PDF
    (`AIE2609_Project.pdf`), `.env` or any secret; other PDFs (e.g. the final
    presentation) may be committed.
  - `output/` is ignored during development; the final outputs generated by the pipeline
    are committed at the end.
- **Required docs:** `README.md` (with the end-to-end run command), `ARCHITECTURE.md`,
  `DATA_MODEL.md`, `IMPLEMENTATION_PLAN.md`, `CLAUDE.md`.
