# J.A.R.V.I.S. — Institutional AI Financial Assistant

A voice-first equity research terminal. Ask about any NSE-listed stock and JARVIS
generates an institutional-grade analysis on **Claude (Opus 4.8)**, grounded on
**live market data**, and auto-builds a **formula-linked Excel model** and an
**institutional PDF** — validated by a Python calc-check layer.

## What it does

- **Ask in plain language** — "long term analysis on Infosys", "should I buy Eternal".
  Sonnet 5 resolves the ticker (recovers renamed/delisted names via live search).
- **Full analysis in chat** — thesis, moat, bull/bear, catalysts, risks, recommendation,
  and the complete DCF **valuation assumptions** (WACC build, 5-year FCF schedule,
  assumption log).
- **Auto-generated deliverables** — a multi-sheet, formula-linked DCF Excel model
  (Assumptions → Model, live cross-sheet formulas) + an institutional PDF.
- **Python validates calcs only** — an independent DCF recompute cross-checks the
  model; a data-recency gate confirms the latest reported quarter.
- **Voice** — Whisper (local, accurate) for input; British-male TTS reads the
  opening and closing of each analysis; speak any time to interrupt.

## Architecture

| Layer | Tech |
|-------|------|
| Backend | Flask (Python 3.9), port 3000 |
| Analysis | Claude API (Opus 4.8 report · Sonnet 5 extraction · Haiku chat) |
| Market data | yfinance (NSE) |
| Model / report | openpyxl (linked Excel) · reportlab (PDF) |
| Validation | independent Python DCF recompute (+ optional `formulas` engine) |
| Voice | faster-whisper (STT) · Web Speech (TTS) |

## Run locally

```bash
cp .env.example .env          # add your ANTHROPIC_API_KEY
pip install -r requirements.txt
python server.py              # http://localhost:3000
```

Or use the desktop launcher (`launcher.py`) / `./start.sh`.

## Configuration (`.env`)

| Var | Purpose |
|-----|---------|
| `ANTHROPIC_API_KEY` | required |
| `REPORT_MODEL` | report model (default `claude-opus-4-8`) |
| `EXTRACT_MODEL` | ticker extraction (default `claude-sonnet-5`) |
| `WHISPER_MODEL` | STT model (default `small.en`) |
| `VALIDATE_FORMULAS` | `1` to also execute Excel formulas in validation (slower) |

---

*Automated research tooling — not investment advice. All figures require
professional verification.*
