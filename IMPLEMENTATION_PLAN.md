# Implementation plan

## Roadmap

Each step is validated by the user before the next one starts.

| Step | Content | Status |
|------|---------|--------|
| 0 | Setup: repository layout, dependency management, test framework | Done |
| 1 | Data audit (read-only): report every anomaly in `news.json` and `sp500.csv` | In review |
| 2 | Data cleaning: handling decided per anomaly class; cleaning module + change log | To do |
| 3.1 | Loading + cleaning → aggregation → CSV writing, with a stub extractor | To do |
| 3.2 | Entity identification | To do |
| 3.3 | Sentiment classification + LLM output validation | To do |
| 3.4 | Usage and cost tracking | To do |
| 3.5 | Docs, then optional challenges if time allows | To do |

## Decision log

### D0.1 — Repository layout (Step 0)
- **Context:** the audit, the cleaning and the pipeline will share code, and the evaluators run the project themselves.
- **Options:** (A) flat package at the root; (B) `src/` layout; (C) loose scripts at the root.
- **Choice:** A — package `sp500_sentiment/`, `tests/`, `data/`, `output/`; run with `python -m sp500_sentiment`.
- **Reason:** runs and tests without an install step; simple imports; shared code stays testable.

### D0.2 — Dependency management and Python version (Step 0)
- **Context:** the spec requires the same results on equivalent inputs, and the evaluators must be able to install the project easily.
- **Options:** (A) `requirements.txt` + pip; (B) `pyproject.toml` + pip; (C) `pyproject.toml` + `uv.lock` (uv); (D) Poetry.
- **Choice:** C, Python ≥ 3.11, with a pip fallback documented in the README.
- **Reason:** exact, locked environment with one command; plain pip still works.
- **Sub-decision — pip fallback mechanism.** Options: (A) commit a `requirements.txt` generated from `uv.lock` by `uv export`; (B) add a build backend and dev extras, install with `pip install -e ".[dev]"`; (C) list packages manually in the README. **Choice:** A, exported without package hashes (shorter file; versions still pinned). **Reason:** pip users get exactly the versions pinned in the lock, with no build backend. Cost: `requirements.txt` must be regenerated after every dependency change (command in `CLAUDE.md`).
- **Note:** the project itself is not installed (no build backend). Runtime dependencies are added only at the step that needs them.

### D0.3 — Test framework (Step 0)
- **Options:** (A) pytest; (B) unittest (stdlib); (C) pytest + hypothesis.
- **Choice:** A. Tests never call the network; LLM responses are faked.
- **Reason:** concise assertions and parametrised tests suit the many anomaly cases. Hypothesis can be added later if property tests (e.g. determinism) are wanted.

### D0.4 — What goes into git (Step 0)
- **Options:** (A) commit the raw inputs, ignore `output/` during development, commit the final outputs at the end; (B) don't commit the inputs; (C) commit inputs and outputs at every step.
- **Choice:** A. The repository is public, which the evaluators explicitly allow. The project brief PDF is never committed, nor is `.env` or any secret.
- **Reason:** the repository is self-contained and reproducible, and the final deliverables are visible.
- **Revision at Step 0 review:** `.gitignore` lists the exact brief name `AIE2609_Project.pdf` instead of `*.pdf`, so that the final presentation PDF can be committed.

### D0.5 — Which docs to create in Step 0
- **Options:** (A) only the docs used now (`CLAUDE.md`, `IMPLEMENTATION_PLAN.md`, `README.md`), the others when they have content; (B) all five as placeholders now.
- **Choice:** A. `ARCHITECTURE.md` and `DATA_MODEL.md` are written in Step 3.
- **Reason:** no placeholders that go stale.

### W1 — Delivery workflow: one pull request per step (Step 0 review)
- **Context:** the user reviews every step before the next one starts.
- **Choice (user instruction):** each step is delivered as one pull request into `main`; the user reviews and merges it before the next step starts, and the next step starts from the updated `main`. Rule recorded in `CLAUDE.md` (section 4, Git).
- **Reason:** one reviewable unit per step, and a history on `main` that matches the roadmap.

### W2 — Additional working rules (Step 0 review)
- **Context:** review of `CLAUDE.md`.
- **Choice (user instruction):** three rules added to `CLAUDE.md` section 1:
  - **No dataset-specific logic:** no behaviour hard-coded for a specific article id, headline or phrase, and no alias or rule added just to fix one article; every rule must be general and justified independently of this dataset.
  - **Tests are not negotiable:** never modify or delete a test to make it pass; fix the code, or stop and explain why the test is wrong.
  - **Verify before claiming done:** run the full test suite and show the output before reporting a step or increment as finished.
- **Reason:** the pipeline must generalise to unseen equivalent inputs, and every claim must be backed by an actual run.

### W3 — Project sizing (Step 1 go)
- **Choice (user instruction):** the whole project is sized for 4–6 hours. Keep each piece compact (for the audit: one simple function per check, no framework, no report styling); if something turns out costly to implement, skip it and say so. Recorded in `CLAUDE.md` rule 5.

### S1.1 — Where the audit report goes (Step 1)
- **Options:** (A) printed only; (B) generated Markdown file, committed and also printed; (C) B plus a JSON file of findings for Step 2.
- **Choice:** B — `reports/data_audit.md`, generated by `python -m sp500_sentiment.audit --out reports/data_audit.md`, never edited by hand.
- **Reason:** reviewable in the PR and reusable as the optional data quality report; JSON would be speculative since Step 2 detects the problems again.

### S1.2 — How to detect homoglyphs (Step 1)
- **Options:** (A) by Unicode script with `unicodedata` (flag every non-Latin letter, mark mixed-script words); (B) Unicode `confusables.txt` table in the repo; (C) small hand-written look-alike table; (D) third-party package.
- **Choice:** A.
- **Reason:** no dependency and complete by construction (every non-Latin letter is reported); how to replace the characters is a Step 2 decision.

### S1.3 — How to detect near-duplicates (Step 1)
- **Options:** (A) exact match after normalisation; (B) A + character similarity (`difflib`); (C) A + Jaccard similarity of 5-word shingles, every pair ≥ 0.5 reported with its score; (D) embeddings or the LLM.
- **Choice:** C.
- **Reason:** standard library, a few lines, fast (4,950 pairs), robust to reordering; reporting scores shows the spread instead of trusting one cut-off.

### S1.4 — Code layout of the audit (Step 1)
- **Options:** (A) a single `audit.py`; (B) `config.py` (spec constants) + `load.py` (raw reading, reused later) + `audit.py` (checks and report), run with `python -m sp500_sentiment.audit`; (C) checks split across several modules.
- **Choice:** B.
- **Reason:** the loading code and spec constants are reused by the cleaning and the pipeline; C would be over-engineered.
- **Dependency:** `tzdata` added as a runtime dependency (approved) so `zoneinfo` works on Windows.
- **Added during implementation:** a generic placeholder-value check (`none`, `null`, `n/a`...), after the audit showed `headquarters = none` in `sp500.csv`; and an overview line listing company names with a parenthesised part that is not a share class (`(The)`, `Lilly (Eli)`), which will matter for matching.

## Spec clarifications from the user

Facts stated by the user. Those about the data were confirmed by the Step 1 audit (`reports/data_audit.md`).

- **Future dates (ambiguity #1):** the latest article is 2026-09-28T16:20, so none is after `as_of`. Keep a validation that flags future dates anyway. *Confirmed: 100 valid dates, latest 2026-09-28T16:20, none after `as_of`.*
- **Time zone (ambiguity #2):** all articles fall between Aug 25 and Sep 28, so all are EDT (US daylight saving time ends in November). Use `zoneinfo` `America/New_York` anyway. *Confirmed: earliest 2026-08-25T06:53, all 100 dates EDT, no non-existent or ambiguous local time.*
- **Dual classes (ambiguity #6):** in `sp500.csv`, GOOGL/FOXA/NWSA are listed before GOOG/FOX/NWS, so "first listed" and the fixed list agree. Map the second classes to the first. *Confirmed: GOOGL/GOOG rows 21/22, FOXA/FOX rows 206/207, NWSA/NWS rows 334/335; BRK.B and BF.B are the only class of their company.*
- **Neutral-only tickers (ambiguity #9):** the spec says one row per ticker appearing in `entities.csv`, so neutral-only tickers appear in `scores.csv` with value 0.
- **Final outputs (ambiguity #11):** commit the final outputs generated by the pipeline.

## Open questions

To be decided at the relevant step:

- **#3** Label for an article that is mixed for one company; whether a subject company can be `neutral`.
- **#4** When a mention counts (passing mentions, indirect references such as "the iPhone maker", named competitors).
- **#5** Source of the brand/subsidiary → parent mapping under "no external data" (LLM knowledge, hand-written alias table, or both).
- **#7** Duplicate articles: count once or each time.
- **#8** Which input differences must not change the result, and the strategy for LLM non-determinism.
- **#10** `gpt-5.6-terra` pricing source, cost-per-article definition, cold run vs. cached run.
