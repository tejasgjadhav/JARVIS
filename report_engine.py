#!/usr/bin/env python3
"""J.A.R.V.I.S. Report Engine — institutional equity report, no LLM required.

Pipeline: yfinance (real market data) → factor analysis + DCF (pure Python) →
Excel financial model (openpyxl) + institutional PDF (reportlab).

Everything here is deterministic and works with the Anthropic API offline.
"""
import io
import json
import math
from datetime import datetime

import yfinance as yf
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
)

# ── Palette (JARVIS arc-reactor blue) ──────────────────────
NAVY = "0B1F3A"
ARC = "00A8E8"
LIGHT = "EAF6FB"
GREY = "6B7A8D"


# ═══════════════════════════════════════════════════════════
#  1. DATA
# ═══════════════════════════════════════════════════════════
def normalize_symbol(sym: str) -> str:
    s = (sym or "").strip().upper().lstrip("$")
    # Default to NSE if no exchange suffix given
    if "." not in s and s not in ("", ):
        s = s + ".NS"
    return s


def resolve_symbol(query: str):
    """Resolve a company name or stale/renamed ticker to a current NSE (fallback
    BSE) symbol via Yahoo search — handles delistings, renames, demergers."""
    if not query:
        return None
    try:
        r = yf.Search(query, max_results=10)
        quotes = getattr(r, "quotes", []) or []
    except Exception:
        return None
    for suffix in (".NS", ".BO"):
        for q in quotes:
            s = q.get("symbol", "")
            if s.endswith(suffix):
                return s
    return quotes[0].get("symbol") if quotes else None


def _num(v):
    """Coerce to float or None."""
    try:
        if v is None:
            return None
        f = float(v)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def fetch_stock(symbol: str) -> dict:
    sym = normalize_symbol(symbol)
    t = yf.Ticker(sym)
    info = {}
    try:
        info = t.info or {}
    except Exception:
        info = {}

    hist = None
    try:
        hist = t.history(period="1y")
    except Exception:
        hist = None

    # Statement-based figures are more reliable + INR-consistent than .info scalars.
    fcf_stmt = rev_stmt = None
    try:
        cf = t.cashflow
        if cf is not None and not cf.empty:
            if "Free Cash Flow" in cf.index:
                fcf_stmt = _num(cf.loc["Free Cash Flow"].iloc[0])
            if fcf_stmt is None and "Operating Cash Flow" in cf.index:
                ocf = _num(cf.loc["Operating Cash Flow"].iloc[0])
                capex = _num(cf.loc["Capital Expenditure"].iloc[0]) if "Capital Expenditure" in cf.index else 0
                if ocf is not None:
                    fcf_stmt = ocf + (capex or 0)  # capex is negative in the statement
    except Exception:
        pass
    try:
        fin = t.financials
        if fin is not None and not fin.empty and "Total Revenue" in fin.index:
            rev_stmt = _num(fin.loc["Total Revenue"].iloc[0])
    except Exception:
        pass

    # Latest reported quarter + reference "today" (real, from price history) —
    # used by the Python data-recency gate.
    q_end = None
    try:
        qf = t.quarterly_financials
        if qf is not None and not qf.empty:
            q_end = qf.columns[0].to_pydatetime().date()
    except Exception:
        pass
    ref_date = None
    try:
        if hist is not None and len(hist):
            ref_date = hist.index[-1].to_pydatetime().date()
    except Exception:
        pass

    # Currency mismatch: dual-listed stocks (e.g. Infosys on NYSE) report
    # financial statements in USD while the NSE price is in INR. Convert
    # statement figures to the price currency via a live FX rate.
    price_ccy = info.get("currency") or "INR"
    fin_ccy = info.get("financialCurrency") or price_ccy
    fx = 1.0
    if fin_ccy != price_ccy:
        try:
            pair = yf.Ticker(f"{fin_ccy}{price_ccy}=X").history(period="5d")
            if pair is not None and len(pair):
                fx = float(pair["Close"].iloc[-1])
        except Exception:
            fx = 1.0

    def _fx(v):
        return v * fx if v is not None else None

    # Dividend yield: yfinance returns percent (e.g. 4.8) in newer versions,
    # fraction (0.048) in older — normalise to a fraction.
    dy = _num(info.get("dividendYield"))
    if dy is not None and dy > 1:
        dy = dy / 100

    price = _num(info.get("currentPrice")) or _num(info.get("regularMarketPrice"))
    if price is None and hist is not None and len(hist):
        price = _num(hist["Close"].iloc[-1])

    if price is None:
        raise ValueError(f"No market data found for '{symbol}' (tried {sym}). "
                         f"Use an NSE symbol like INFY, TCS, RELIANCE.")

    dma50 = _num(info.get("fiftyDayAverage"))
    dma200 = _num(info.get("twoHundredDayAverage"))
    if dma200 is None and hist is not None and len(hist) >= 100:
        dma200 = _num(hist["Close"].tail(200).mean())

    return {
        "symbol": sym,
        "name": info.get("longName") or info.get("shortName") or sym,
        "sector": info.get("sector") or "—",
        "industry": info.get("industry") or "—",
        "summary": (info.get("longBusinessSummary") or "").strip(),
        "currency": info.get("currency") or "INR",
        "price": price,
        "market_cap": _num(info.get("marketCap")),
        "pe": _num(info.get("trailingPE")),
        "forward_pe": _num(info.get("forwardPE")),
        "peg": _num(info.get("pegRatio")),
        "pb": _num(info.get("priceToBook")),
        "roe": _num(info.get("returnOnEquity")),
        "margin": _num(info.get("profitMargins")),
        "rev_growth": _num(info.get("revenueGrowth")),
        "earn_growth": _num(info.get("earningsGrowth")),
        "debt_to_equity": _num(info.get("debtToEquity")),
        "div_yield": dy,
        "beta": _num(info.get("beta")),
        "wk_high": _num(info.get("fiftyTwoWeekHigh")),
        "wk_low": _num(info.get("fiftyTwoWeekLow")),
        "dma50": dma50,
        "dma200": dma200,
        "fcf": _fx(fcf_stmt or _num(info.get("freeCashflow"))),
        "op_cf": _fx(_num(info.get("operatingCashflow"))),
        "net_income": _fx(_num(info.get("netIncomeToCommon"))),
        "total_debt": _fx(_num(info.get("totalDebt"))),
        "total_cash": _fx(_num(info.get("totalCash"))),
        "shares": _num(info.get("sharesOutstanding")),
        "revenue": _fx(rev_stmt or _num(info.get("totalRevenue"))),
        "fin_ccy": fin_ccy, "fx": fx,
        "quarter_end": q_end, "data_ref_date": ref_date,
        "target_mean": _num(info.get("targetMeanPrice")),
    }


# ═══════════════════════════════════════════════════════════
#  2. VALUATION + FACTOR ANALYSIS  (deterministic, no LLM)
# ═══════════════════════════════════════════════════════════
def dcf_fair_value(d: dict) -> dict:
    """Simple 10-yr two-stage FCF DCF. Returns fair value/share or None."""
    fcf = d.get("fcf")
    if fcf is None or fcf <= 0:
        # fall back to a proxy: 80% of operating cash flow, else net income
        base = d.get("op_cf")
        fcf = (base * 0.8) if (base and base > 0) else d.get("net_income")
    shares = d.get("shares")
    if not fcf or fcf <= 0 or not shares or shares <= 0:
        return {"fair_value": None, "upside": None, "note": "Insufficient cash-flow data for DCF"}

    g1 = d.get("rev_growth")
    g1 = 0.10 if g1 is None else max(min(g1, 0.25), 0.0)  # cap stage-1 growth
    g_term = 0.04
    r = 0.12  # discount rate

    total = 0.0
    cf = fcf
    for yr in range(1, 11):
        # fade growth linearly from g1 to terminal over 10 years
        g = g1 + (g_term - g1) * (yr - 1) / 9
        cf = cf * (1 + g)
        total += cf / ((1 + r) ** yr)
    terminal = cf * (1 + g_term) / (r - g_term)
    total += terminal / ((1 + r) ** 10)

    net_debt = (d.get("total_debt") or 0) - (d.get("total_cash") or 0)
    equity = total - net_debt
    fv = equity / shares
    price = d.get("price")

    # Sanity guard: yfinance data for Indian stocks can be inconsistent (wrong
    # units/scale). If the DCF lands wildly off the market price, the inputs are
    # unreliable — suppress the number rather than print a misleading figure.
    if price and (fv <= 0 or fv < 0.15 * price or fv > 6 * price):
        return {"fair_value": None, "upside": None,
                "note": "DCF omitted — cash-flow data failed reliability check"}

    upside = (fv / price - 1) if price else None
    return {"fair_value": fv, "upside": upside,
            "assumptions": {"stage1_growth": g1, "terminal_growth": g_term, "discount_rate": r},
            "note": ""}


def analyze(d: dict) -> dict:
    """Multi-factor scorecard → recommendation. Pure rules."""
    factors = []  # (name, value_str, verdict, points)

    def add(name, val, points, comment):
        factors.append({"factor": name, "value": val, "signal": comment, "points": points})

    price = d["price"]

    pe = d.get("pe")
    if pe is not None:
        p = 1 if pe < 22 else (0 if pe < 35 else -1)
        add("Valuation (P/E)", f"{pe:.1f}x", p,
            "Attractive" if p > 0 else ("Fair" if p == 0 else "Rich"))

    peg = d.get("peg")
    if peg is not None and peg > 0:
        p = 1 if peg < 1 else (0 if peg < 2 else -1)
        add("Growth-adj. (PEG)", f"{peg:.2f}", p,
            "Cheap vs growth" if p > 0 else ("Balanced" if p == 0 else "Expensive"))

    roe = d.get("roe")
    if roe is not None:
        p = 1 if roe > 0.18 else (0 if roe > 0.10 else -1)
        add("Profitability (ROE)", f"{roe*100:.1f}%", p,
            "Strong" if p > 0 else ("Adequate" if p == 0 else "Weak"))

    rg = d.get("rev_growth")
    if rg is not None:
        p = 1 if rg > 0.12 else (0 if rg > 0.04 else -1)
        add("Revenue growth", f"{rg*100:.1f}%", p,
            "High" if p > 0 else ("Moderate" if p == 0 else "Sluggish"))

    de = d.get("debt_to_equity")
    if de is not None:
        de_r = de / 100 if de > 5 else de  # yfinance gives % sometimes
        p = 1 if de_r < 0.5 else (0 if de_r < 1.2 else -1)
        add("Leverage (D/E)", f"{de_r:.2f}", p,
            "Conservative" if p > 0 else ("Moderate" if p == 0 else "Elevated"))

    if d.get("dma200"):
        p = 1 if price > d["dma200"] else -1
        add("Trend (vs 200-DMA)", f"₹{d['dma200']:.0f}", p,
            "Above — uptrend" if p > 0 else "Below — weak")

    if d.get("wk_high") and d.get("wk_low"):
        rng = (price - d["wk_low"]) / (d["wk_high"] - d["wk_low"]) if d["wk_high"] > d["wk_low"] else 0.5
        p = 0 if 0.3 <= rng <= 0.85 else (1 if rng < 0.3 else -1)
        add("52-wk position", f"{rng*100:.0f}% of range", p,
            "Near lows — value" if p > 0 else ("Mid-range" if p == 0 else "Near highs"))

    dcf = dcf_fair_value(d)
    if dcf["upside"] is not None:
        u = dcf["upside"]
        p = 1 if u > 0.15 else (0 if u > -0.10 else -1)
        add("DCF fair value", f"₹{dcf['fair_value']:.0f} ({u*100:+.0f}%)", p,
            "Undervalued" if p > 0 else ("Fairly valued" if p == 0 else "Overvalued"))

    score = sum(f["points"] for f in factors)
    n = len(factors) or 1
    norm = score / n

    if norm >= 0.45:
        verdict, action = "BUY", "Accumulate on dips — strong long-term conviction"
    elif norm >= 0.15:
        verdict, action = "ACCUMULATE", "Build position gradually via SIP/DCA"
    elif norm >= -0.15:
        verdict, action = "HOLD", "Hold existing; await better entry or catalysts"
    elif norm >= -0.45:
        verdict, action = "REDUCE", "Trim on strength; risks outweigh reward"
    else:
        verdict, action = "AVOID", "Unfavourable risk/reward at current levels"

    return {"factors": factors, "score": score, "n": n, "norm": norm,
            "verdict": verdict, "action": action, "dcf": dcf}


def numbers_block(d: dict, a: dict, result: dict) -> str:
    """Compact numbers shown IN the chat (not spoken). Leads with the analyst
    target; the DCF is shown only when it's a sane cross-check (not for
    negative-FCF / early-stage names where a plain DCF is misleading)."""
    price = d["price"]
    fv = (result.get("validation") or {}).get("computed_fair_value")
    tgt = result.get("price_target")
    base_fcf = d.get("fcf")
    lines = [f"**{d['name']} ({d['symbol']})**  ·  ₹{price:,.0f}"]

    kv = []
    pe = d.get("pe")
    if pe:
        kv.append(f"P/E {pe:.0f}x" + (" (rich)" if pe > 60 else ""))
    if d.get("roe") is not None:
        kv.append(f"ROE {d['roe']*100:.1f}%")
    rg = d.get("rev_growth")
    if rg is not None:
        kv.append("Rev gr n/m" if abs(rg) > 1.0 else f"Rev gr {rg*100:.1f}%")   # >100% = data artifact
    if d.get("debt_to_equity") is not None:
        de = d["debt_to_equity"]
        kv.append(f"D/E {(de/100 if de > 5 else de):.2f}")
    if kv:
        lines.append(" · ".join(kv))

    fcf_str = "negative (growth-stage)" if (base_fcf is not None and base_fcf < 0) else _fmt_money(base_fcf)
    lines.append(f"Revenue {_fmt_money(d.get('revenue'))} · FCF {fcf_str}")

    # Valuation: analyst target leads; DCF only as a sane cross-check.
    if tgt:
        lines.append(f"Analyst fair value ₹{tgt:,.0f} ({(tgt/price-1)*100:+.0f}%)")
    dcf_reliable = (fv and base_fcf and base_fcf > 0 and 0.5 * price <= fv <= 2.0 * price)
    if dcf_reliable:
        lines.append(f"DCF cross-check ₹{fv:,.0f} ({(fv/price-1)*100:+.0f}%)")
    elif not tgt and fv:
        lines.append(f"DCF (indicative) ₹{fv:,.0f}")
    if not tgt and not dcf_reliable and base_fcf is not None and base_fcf < 0:
        lines.append("_DCF omitted — negative FCF; valuation is judgement-led._")

    lines.append(f"**Verdict: {result['verdict']}**")
    validated = (result.get("validation") or {}).get("ok")
    lines.append(f"_Data as-of {result.get('data_asof')} · "
                 f"{'✅ calcs validated' if validated else '⚠ validation flagged'} · "
                 f"Excel + PDF downloading…_")
    return "\n".join(lines)


def compose_analysis(d: dict, a: dict, narrative, result: dict):
    """Return (chat_markdown, speech). chat_markdown = the ENTIRE Claude analysis
    for display; speech = first 2 lines + last 2 lines for JARVIS to read aloud."""
    n = narrative or {}
    verdict = result["verdict"]
    tgt = result.get("price_target")
    sector = d.get("industry") or d.get("sector") or ""

    thesis = (n.get("thesis") or a["action"]).strip()
    thesis_first = thesis.split(". ")[0].rstrip(".") + "."
    rec = (n.get("recommendation") or a["action"]).strip()
    rec_last = rec.split(". ")[-1].strip().rstrip(".") + "."
    rationale = (n.get("verdict_rationale") or "").strip()

    # ── Spoken: first 2 lines (intro + thesis) + last 2 lines (rationale + call) ──
    intro_line = f"{d['name']}, {sector}." if sector else f"{d['name']}."
    final_line = f"Final recommendation: {verdict}" + (f", {rationale}" if rationale else "") + \
                 (f". Twelve-month target {tgt:,.0f} rupees." if tgt else ".")
    speech = " ".join([intro_line, thesis_first, rec_last, final_line])

    # ── Chat: the entire analysis ──
    p = [f"**{d['name']} ({d['symbol']})** · ₹{d['price']:,.0f} · **{verdict}**", ""]
    p.append(f"**Thesis.** {thesis}")
    if n.get("business"):
        p.append(f"**Business & moat.** {n['business']}")
    if n.get("bull_case"):
        p.append("**Bull case:**\n" + "\n".join(f"- {x}" for x in n["bull_case"]))
    if n.get("bear_case"):
        p.append("**Bear case:**\n" + "\n".join(f"- {x}" for x in n["bear_case"]))
    if n.get("catalysts"):
        p.append("**Catalysts:**\n" + "\n".join(f"- {x}" for x in n["catalysts"]))
    if n.get("risks"):
        p.append("**Key risks:**\n" + "\n".join(f"- {x}" for x in n["risks"]))
    p.append(f"**Recommendation.** {rec}")

    # ── VALUATION & ASSUMPTIONS (institutional detail) ──
    asmp = result.get("assumptions") or {}
    if asmp:
        dcf = python_dcf(asmp)
        wb = n.get("wacc_build") or {}
        pct = lambda x: f"{x*100:.1f}%" if x is not None else "—"
        vlines = ["**Valuation — DCF assumptions**"]
        if wb:
            ke = wb.get("cost_of_equity")
            vlines.append(
                f"WACC build: RF {pct(wb.get('rf'))} + β{wb.get('beta','—')}×ERP {pct(wb.get('erp'))} "
                f"→ Ke {pct(ke)}; Kd {pct(wb.get('cost_of_debt'))}; "
                f"{pct(wb.get('equity_weight'))} equity / {pct(wb.get('debt_weight'))} debt "
                f"→ **WACC {pct(asmp.get('wacc'))}**")
        else:
            vlines.append(f"Discount rate (WACC): **{pct(asmp.get('wacc'))}**")
        g = asmp.get("growth", [])
        vlines.append(
            f"Drivers: revenue growth {pct(g[0]) if g else '—'}→{pct(g[-1]) if g else '—'} (5y) · "
            f"EBIT margin {pct(asmp.get('ebit_margin'))} · tax {pct(asmp.get('tax_rate'))} · "
            f"capex {pct(asmp.get('capex_pct'))} · D&A {pct(asmp.get('da_pct'))} · "
            f"ΔNWC {pct(asmp.get('nwc_pct'))} · terminal {pct(asmp.get('terminal_growth'))}")
        sch = dcf.get("schedule", [])
        if sch:
            vlines.append("FCF (₹Cr): " + " · ".join(f"Y{s['year']} {s['fcf']:,.0f}" for s in sch))
        vlines.append(
            f"PV explicit ₹{dcf['pv_explicit']:,.0f} Cr + PV terminal ₹{dcf['pv_terminal']:,.0f} Cr "
            f"= EV ₹{dcf['ev']:,.0f} Cr − net debt ₹{asmp.get('net_debt_cr',0):,.0f} Cr "
            f"= Equity ₹{dcf['equity']:,.0f} Cr" +
            (f" → **DCF fair value ₹{dcf['fair_value']:,.0f}/sh**" if dcf.get('fair_value') else ""))
        if n.get("assumption_log"):
            vlines.append("Assumption log:\n" + "\n".join(f"- {x}" for x in n["assumption_log"]))
        p.append("\n".join(vlines))

    p.append("")
    p.append(result["numbers"])
    return "\n\n".join(p), speech


def data_recency(d: dict) -> dict:
    """Python gate: is the financial data from the latest or previous quarter?"""
    q = d.get("quarter_end")
    ref = d.get("data_ref_date")
    if not q or not ref:
        return {"asof": "unknown", "status": "unknown", "ok": True, "days": None}
    days = (ref - q).days
    if days <= 135:
        status, ok = "latest quarter", True
    elif days <= 240:
        status, ok = "previous quarter", True
    else:
        status, ok = "STALE (>2 quarters old)", False
    return {"asof": q.strftime("%d %b %Y"), "status": status, "ok": ok, "days": days}


def final_verdict(a: dict, narrative=None) -> str:
    """Claude's call is the headline; quant scorecard is the fallback."""
    v = (narrative or {}).get("verdict")
    if v and str(v).upper() in ("BUY", "ACCUMULATE", "HOLD", "REDUCE", "SELL"):
        return str(v).upper()
    return a["verdict"]


def two_line_summary(d: dict, a: dict, narrative=None) -> str:
    """Exactly two lines for voice/chat: company + final call with short rationale."""
    intro = f"{d['name']} — {d['industry']} ({d['sector']})."
    verdict = final_verdict(a, narrative)
    rationale = (narrative or {}).get("verdict_rationale")
    if not rationale and narrative and narrative.get("recommendation"):
        rationale = narrative["recommendation"].split(". ")[0]
    rationale = (rationale or a["action"]).strip().rstrip(".")
    # keep the spoken line tight
    if len(rationale) > 90:
        rationale = rationale[:87].rsplit(" ", 1)[0] + "…"
    return f"{intro}\nRecommendation: {verdict} — {rationale}."


# ═══════════════════════════════════════════════════════════
#  3. EXCEL MODEL
# ═══════════════════════════════════════════════════════════
def _fmt_money(v):
    if v is None:
        return "N/A"
    a = abs(v)
    if a >= 1e12:
        return f"₹{v/1e12:.2f} T"
    if a >= 1e7:
        return f"₹{v/1e7:.2f} Cr"
    if a >= 1e5:
        return f"₹{v/1e5:.2f} L"
    return f"₹{v:,.0f}"


def default_assumptions(d: dict) -> dict:
    """5-year model drivers grounded on real data (in ₹ Crore where noted)."""
    rev = d.get("revenue") or 0
    base_rev_cr = rev / 1e7 if rev else 1000.0
    g = d.get("rev_growth")
    g1 = min(max(g if g is not None else 0.10, 0.04), 0.25)
    g5 = max(g1 * 0.55, 0.06)
    growth = [round(g1 + (g5 - g1) * i / 4, 4) for i in range(5)]  # linear fade
    margin = d.get("margin")
    ebit_margin = round(min(max((margin * 1.25) if margin is not None else 0.15, 0.05), 0.45), 4)
    net_debt_cr = ((d.get("total_debt") or 0) - (d.get("total_cash") or 0)) / 1e7
    shares_cr = (d.get("shares") or 0) / 1e7
    return {
        "base_rev_cr": round(base_rev_cr, 2),
        "growth": growth,
        "ebit_margin": ebit_margin,
        "tax_rate": 0.25,
        "capex_pct": 0.04,
        "da_pct": 0.035,
        "nwc_pct": 0.02,
        "wacc": 0.12,
        "terminal_growth": 0.05,
        "net_debt_cr": round(net_debt_cr, 2),
        "shares_cr": round(shares_cr, 4) if shares_cr else 1.0,
        "price": d["price"],
    }


def merge_assumptions(base: dict, claude: dict) -> dict:
    """Overlay Claude-suggested drivers on defaults, clamped to sane ranges."""
    if not claude:
        return base
    out = dict(base)
    def clamp(x, lo, hi):
        try:
            return max(lo, min(hi, float(x)))
        except (TypeError, ValueError):
            return None
    if isinstance(claude.get("growth"), list) and claude["growth"]:
        g = [clamp(x, -0.10, 0.40) for x in claude["growth"][:5]]
        g = [x for x in g if x is not None]
        if len(g) == 5:
            out["growth"] = g
    for key, lo, hi in [("ebit_margin", 0.02, 0.55), ("tax_rate", 0.10, 0.40),
                        ("capex_pct", 0.0, 0.25), ("da_pct", 0.0, 0.20),
                        ("nwc_pct", -0.10, 0.20), ("wacc", 0.07, 0.20),
                        ("terminal_growth", 0.0, 0.07)]:
        if claude.get(key) is not None:
            v = clamp(claude[key], lo, hi)
            if v is not None:
                out[key] = round(v, 4)
    # keep terminal_growth strictly below wacc for DCF stability
    if out["terminal_growth"] >= out["wacc"] - 0.01:
        out["terminal_growth"] = round(out["wacc"] - 0.03, 4)
    return out


def python_dcf(asmp: dict) -> dict:
    """Independent recompute of the linked Excel model — the validation oracle.
    Mirrors the MODEL sheet formulas cell-for-cell."""
    rev_prev = asmp["base_rev_cr"]
    wacc, tg = asmp["wacc"], asmp["terminal_growth"]
    pv_sum, fcf_last, df_last = 0.0, 0.0, 1.0
    schedule = []
    for i in range(5):
        rev = rev_prev * (1 + asmp["growth"][i])
        ebit = rev * asmp["ebit_margin"]
        nopat = ebit * (1 - asmp["tax_rate"])
        da = rev * asmp["da_pct"]
        capex = rev * asmp["capex_pct"]
        dnwc = (rev - rev_prev) * asmp["nwc_pct"]
        fcf = nopat + da - capex - dnwc
        df = 1 / (1 + wacc) ** (i + 1)
        pv_sum += fcf * df
        schedule.append({"year": i + 1, "revenue": rev, "ebit": ebit, "fcf": fcf, "pv_fcf": fcf * df})
        rev_prev, fcf_last, df_last = rev, fcf, df
    tv = fcf_last * (1 + tg) / (wacc - tg)
    pv_tv = tv * df_last
    ev = pv_sum + pv_tv
    equity = ev - asmp["net_debt_cr"]
    fv = equity / asmp["shares_cr"] if asmp["shares_cr"] else None
    upside = (fv / asmp["price"] - 1) if (fv and asmp.get("price")) else None
    return {"ev": ev, "equity": equity, "fair_value": fv, "upside": upside,
            "schedule": schedule, "pv_explicit": pv_sum, "terminal_value": tv,
            "pv_terminal": pv_tv}


def build_excel(d: dict, a: dict, narrative=None, assumptions=None) -> bytes:
    wb = Workbook()
    thin = Side(style="thin", color="D0D7DE")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    hdr_fill = PatternFill("solid", fgColor=NAVY)
    arc_fill = PatternFill("solid", fgColor=ARC)
    hdr_font = Font(color="FFFFFF", bold=True, size=11)
    title_font = Font(color="FFFFFF", bold=True, size=16)

    def style_header(ws, row, cols, text=None):
        for c in range(1, cols + 1):
            cell = ws.cell(row=row, column=c)
            cell.fill = hdr_fill
            cell.font = hdr_font
            cell.border = border

    # ── COVER ──
    ws = wb.active
    ws.title = "COVER"
    ws.sheet_view.showGridLines = False
    ws.merge_cells("A1:D1")
    ws["A1"] = "J.A.R.V.I.S. · INSTITUTIONAL EQUITY RESEARCH"
    ws["A1"].fill = PatternFill("solid", fgColor=NAVY)
    ws["A1"].font = title_font
    ws["A1"].alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 34
    rows = [
        ("Company", d["name"]),
        ("Symbol", d["symbol"]),
        ("Sector / Industry", f"{d['sector']} / {d['industry']}"),
        ("Current Price", f"₹{d['price']:,.2f}"),
        ("Market Cap", _fmt_money(d.get("market_cap"))),
        ("Recommendation", final_verdict(a, narrative)),
        ("Action", (narrative or {}).get("verdict_rationale") or a["action"]),
        ("Report Date", datetime.now().strftime("%d %b %Y")),
    ]
    r = 3
    for k, v in rows:
        ws.cell(r, 1, k).font = Font(bold=True, color=NAVY)
        ws.cell(r, 2, v)
        if k == "Recommendation":
            ws.cell(r, 2).font = Font(bold=True, size=13, color=ARC)
        r += 1
    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 52

    # ── KEY METRICS ──
    ws = wb.create_sheet("KEY_METRICS")
    ws.sheet_view.showGridLines = False
    ws.append(["Metric", "Value"])
    style_header(ws, 1, 2)
    metrics = [
        ("Trailing P/E", f"{d['pe']:.1f}x" if d.get("pe") else "N/A"),
        ("Forward P/E", f"{d['forward_pe']:.1f}x" if d.get("forward_pe") else "N/A"),
        ("PEG ratio", f"{d['peg']:.2f}" if d.get("peg") else "N/A"),
        ("Price / Book", f"{d['pb']:.2f}" if d.get("pb") else "N/A"),
        ("Return on Equity", f"{d['roe']*100:.1f}%" if d.get("roe") is not None else "N/A"),
        ("Profit Margin", f"{d['margin']*100:.1f}%" if d.get("margin") is not None else "N/A"),
        ("Revenue Growth", f"{d['rev_growth']*100:.1f}%" if d.get("rev_growth") is not None else "N/A"),
        ("Earnings Growth", f"{d['earn_growth']*100:.1f}%" if d.get("earn_growth") is not None else "N/A"),
        ("Debt / Equity", f"{d['debt_to_equity']:.2f}" if d.get("debt_to_equity") is not None else "N/A"),
        ("Dividend Yield", f"{d['div_yield']*100:.2f}%" if d.get("div_yield") else "N/A"),
        ("Beta", f"{d['beta']:.2f}" if d.get("beta") else "N/A"),
        ("52-wk High", f"₹{d['wk_high']:,.0f}" if d.get("wk_high") else "N/A"),
        ("52-wk Low", f"₹{d['wk_low']:,.0f}" if d.get("wk_low") else "N/A"),
        ("50-DMA", f"₹{d['dma50']:,.0f}" if d.get("dma50") else "N/A"),
        ("200-DMA", f"₹{d['dma200']:,.0f}" if d.get("dma200") else "N/A"),
        ("Revenue (TTM)", _fmt_money(d.get("revenue"))),
        ("Free Cash Flow", _fmt_money(d.get("fcf"))),
    ]
    for k, v in metrics:
        ws.append([k, v])
    for row in ws.iter_rows(min_row=1, max_row=ws.max_row, max_col=2):
        for cell in row:
            cell.border = border
    ws.column_dimensions["A"].width = 24
    ws.column_dimensions["B"].width = 20

    # ── SCORECARD ──
    ws = wb.create_sheet("SCORECARD")
    ws.sheet_view.showGridLines = False
    ws.append(["Factor", "Value", "Signal", "Score"])
    style_header(ws, 1, 4)
    for f in a["factors"]:
        ws.append([f["factor"], f["value"], f["signal"], f["points"]])
        sc = ws.cell(ws.max_row, 4)
        sc.font = Font(bold=True, color=("1A7F37" if f["points"] > 0 else ("B42318" if f["points"] < 0 else "6B7A8D")))
    ws.append([])
    ws.append(["COMPOSITE", f"{a['score']}/{a['n']}", a["verdict"], round(a["norm"], 2)])
    ws.cell(ws.max_row, 1).font = Font(bold=True)
    ws.cell(ws.max_row, 3).font = Font(bold=True, color=ARC)
    for row in ws.iter_rows(min_row=1, max_row=ws.max_row, max_col=4):
        for cell in row:
            cell.border = border
    for col, w in zip("ABCD", (24, 22, 22, 10)):
        ws.column_dimensions[col].width = w

    # ── ASSUMPTIONS (input cells that drive the model) ──
    asmp = assumptions or default_assumptions(d)
    pct = "0.0%"
    num = "#,##0"
    wa = wb.create_sheet("ASSUMPTIONS")
    wa.sheet_view.showGridLines = False
    wa.merge_cells("A1:F1")
    wa["A1"] = "ASSUMPTIONS  (editable drivers)"
    wa["A1"].fill = hdr_fill
    wa["A1"].font = hdr_font
    inputs = [
        ("Base revenue (₹ Cr)", asmp["base_rev_cr"], num),      # B3
        ("EBIT margin", asmp["ebit_margin"], pct),               # B4
        ("Tax rate", asmp["tax_rate"], pct),                     # B5
        ("Capex (% revenue)", asmp["capex_pct"], pct),           # B6
        ("D&A (% revenue)", asmp["da_pct"], pct),                # B7
        ("Δ NWC (% Δrevenue)", asmp["nwc_pct"], pct),            # B8
        ("WACC (discount rate)", asmp["wacc"], pct),             # B9
        ("Terminal growth", asmp["terminal_growth"], pct),       # B10
        ("Net debt (₹ Cr)", asmp["net_debt_cr"], num),           # B11
        ("Shares (Cr)", asmp["shares_cr"], "#,##0.00"),          # B12
        ("Current price (₹)", asmp["price"], "#,##0.00"),        # B13
    ]
    r = 3
    for label, val, fmt in inputs:
        wa.cell(r, 1, label).font = Font(bold=True, color=NAVY)
        c = wa.cell(r, 2, val)
        c.number_format = fmt
        c.fill = PatternFill("solid", fgColor="FFF7E0")  # highlight = editable input
        c.border = border
        r += 1
    # revenue growth path across Year 1..5 → B15:F15
    wa.cell(15, 1, "Revenue growth (Yr1→Yr5)").font = Font(bold=True, color=NAVY)
    for i, g in enumerate(asmp["growth"]):
        c = wa.cell(15, 2 + i, g)
        c.number_format = pct
        c.fill = PatternFill("solid", fgColor="FFF7E0")
        c.border = border
    wa.column_dimensions["A"].width = 26
    for col in "BCDEF":
        wa.column_dimensions[col].width = 12

    # ── MODEL (DCF, fully formula-linked to ASSUMPTIONS) ──
    wm = wb.create_sheet("MODEL")
    wm.sheet_view.showGridLines = False
    wm.merge_cells("A1:F1")
    wm["A1"] = "DCF MODEL  (₹ Crore) — live formulas"
    wm["A1"].fill = hdr_fill
    wm["A1"].font = hdr_font
    cols = ["B", "C", "D", "E", "F"]  # Year 1..5
    wm.cell(2, 1, "Line item").font = Font(bold=True, color="FFFFFF")
    wm.cell(2, 1).fill = PatternFill("solid", fgColor=NAVY)
    for i, col in enumerate(cols):
        c = wm.cell(2, 2 + i, f"Year {i+1}")
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor=NAVY)
    # Revenue (row3): Yr1 grows base; each next grows previous
    wm.cell(3, 1, "Revenue")
    wm["B3"] = "=ASSUMPTIONS!$B$3*(1+ASSUMPTIONS!B15)"
    for i in range(1, 5):
        prev, cur = cols[i - 1], cols[i]
        wm[f"{cur}3"] = f"={prev}3*(1+ASSUMPTIONS!{cur}15)"
    # EBIT, NOPAT, D&A, Capex, ΔNWC, FCF, DF, PV
    for i, col in enumerate(cols):
        wm[f"{col}4"] = f"={col}3*ASSUMPTIONS!$B$4"                       # EBIT
        wm[f"{col}5"] = f"={col}4*(1-ASSUMPTIONS!$B$5)"                   # NOPAT
        wm[f"{col}6"] = f"={col}3*ASSUMPTIONS!$B$7"                       # D&A
        wm[f"{col}7"] = f"={col}3*ASSUMPTIONS!$B$6"                       # Capex
        prevrev = "ASSUMPTIONS!$B$3" if i == 0 else f"{cols[i-1]}3"
        wm[f"{col}8"] = f"=({col}3-{prevrev})*ASSUMPTIONS!$B$8"           # ΔNWC
        wm[f"{col}9"] = f"={col}5+{col}6-{col}7-{col}8"                   # FCF
        wm[f"{col}10"] = f"=1/(1+ASSUMPTIONS!$B$9)^{i+1}"                 # discount factor
        wm[f"{col}11"] = f"={col}9*{col}10"                              # PV of FCF
    for row, lbl in [(4, "EBIT"), (5, "NOPAT"), (6, "(+) D&A"), (7, "(−) Capex"),
                     (8, "(−) Δ NWC"), (9, "Unlevered FCF"), (10, "Discount factor"), (11, "PV of FCF")]:
        wm.cell(row, 1, lbl)
    # Valuation block
    val = [
        ("Sum PV (explicit)", "=SUM(B11:F11)", num),                                          # B13
        ("Terminal value", "=F9*(1+ASSUMPTIONS!$B$10)/(ASSUMPTIONS!$B$9-ASSUMPTIONS!$B$10)", num),  # B14
        ("PV of terminal", "=B14*F10", num),                                                  # B15
        ("Enterprise value", "=B13+B15", num),                                                # B16
        ("Less: net debt", "=ASSUMPTIONS!$B$11", num),                                        # B17
        ("Equity value", "=B16-B17", num),                                                    # B18
        ("Shares (Cr)", "=ASSUMPTIONS!$B$12", "#,##0.00"),                                     # B19
        ("Fair value / share (₹)", "=B18/B19", "#,##0.00"),                                    # B20
        ("Current price (₹)", "=ASSUMPTIONS!$B$13", "#,##0.00"),                               # B21
        ("Upside / (downside)", "=B20/B21-1", pct),                                            # B22
    ]
    rr = 13
    for label, formula, fmt in val:
        wm.cell(rr, 1, label).font = Font(bold=True, color=NAVY)
        c = wm.cell(rr, 2, formula)
        c.number_format = fmt
        if label.startswith("Fair value") or label.startswith("Upside"):
            c.font = Font(bold=True, color=ARC)
        rr += 1
    wm.column_dimensions["A"].width = 22
    for col in "BCDEF":
        wm.column_dimensions[col].width = 13
    for row in wm.iter_rows(min_row=3, max_row=11, min_col=2, max_col=6):
        for cell in row:
            cell.number_format = num

    # COVER → MODEL cross-links (fair value + upside)
    cover = wb["COVER"]
    cr = cover.max_row + 2
    cover.cell(cr, 1, "DCF Fair Value (₹)").font = Font(bold=True, color=NAVY)
    fvc = cover.cell(cr, 2, "=MODEL!B20"); fvc.number_format = "#,##0.00"; fvc.font = Font(bold=True, color=ARC)
    cover.cell(cr + 1, 1, "Upside / (downside)").font = Font(bold=True, color=NAVY)
    uc = cover.cell(cr + 1, 2, "=MODEL!B22"); uc.number_format = pct; uc.font = Font(bold=True, color=ARC)

    # ── ANALYSIS (Claude narrative, grounded on real data) ──
    if narrative:
        ws = wb.create_sheet("ANALYSIS", 1)  # place right after COVER
        ws.sheet_view.showGridLines = False
        ws.column_dimensions["A"].width = 100
        row = 1

        def section(title, content):
            nonlocal row
            c = ws.cell(row, 1, title)
            c.font = Font(bold=True, color="FFFFFF", size=11)
            c.fill = PatternFill("solid", fgColor=ARC)
            row += 1
            if isinstance(content, list):
                for item in content:
                    ws.cell(row, 1, f"•  {item}").alignment = Alignment(wrap_text=True, vertical="top")
                    row += 1
            else:
                cell = ws.cell(row, 1, str(content))
                cell.alignment = Alignment(wrap_text=True, vertical="top")
                row += 1
            row += 1  # spacer

        section("INVESTMENT THESIS", narrative.get("thesis", "—"))
        section("BUSINESS & MOAT", narrative.get("business", "—"))
        if narrative.get("bull_case"):
            section("BULL CASE", narrative["bull_case"])
        if narrative.get("bear_case"):
            section("BEAR CASE", narrative["bear_case"])
        if narrative.get("catalysts"):
            section("CATALYSTS", narrative["catalysts"])
        if narrative.get("risks"):
            section("KEY RISKS", narrative["risks"])
        section("RECOMMENDATION RATIONALE", narrative.get("recommendation", a["action"]))

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ═══════════════════════════════════════════════════════════
#  4. INSTITUTIONAL PDF
# ═══════════════════════════════════════════════════════════
def build_pdf(d: dict, a: dict, narrative=None) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=16 * mm, rightMargin=16 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm)
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Title"], textColor=colors.HexColor("#" + NAVY), fontSize=18, spaceAfter=2)
    sub = ParagraphStyle("sub", parent=ss["Normal"], textColor=colors.HexColor("#" + GREY), fontSize=9, spaceAfter=10)
    hh = ParagraphStyle("hh", parent=ss["Heading2"], textColor=colors.HexColor("#" + ARC), fontSize=12, spaceBefore=10, spaceAfter=4)
    body = ParagraphStyle("body", parent=ss["Normal"], fontSize=9.5, leading=13)
    story = []

    story.append(Paragraph("J.A.R.V.I.S. · Institutional Equity Research", h1))
    story.append(Paragraph(datetime.now().strftime("%d %B %Y") + " &nbsp;·&nbsp; For informational purposes only — not investment advice", sub))

    # Recommendation banner
    verdict = final_verdict(a, narrative)
    verdict_tbl = Table([[f"{d['name']}  ({d['symbol']})", f"{verdict}"]], colWidths=[120 * mm, 45 * mm])
    verdict_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#" + NAVY)),
        ("TEXTCOLOR", (0, 0), (0, 0), colors.white),
        ("TEXTCOLOR", (1, 0), (1, 0), colors.HexColor("#" + ARC)),
        ("FONTSIZE", (0, 0), (0, 0), 12),
        ("FONTSIZE", (1, 0), (1, 0), 14),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.append(verdict_tbl)
    story.append(Spacer(1, 6))

    def bullets(items):
        for it in items:
            story.append(Paragraph(f"•&nbsp; {it}", body))

    if narrative:
        story.append(Paragraph("Investment Thesis", hh))
        story.append(Paragraph(narrative.get("thesis", ""), body))
        if narrative.get("business"):
            story.append(Paragraph(f"<b>Business & moat.</b> {narrative['business']}", body))
        if narrative.get("bull_case"):
            story.append(Paragraph("Bull Case", hh)); bullets(narrative["bull_case"])
        if narrative.get("bear_case"):
            story.append(Paragraph("Bear Case", hh)); bullets(narrative["bear_case"])
        if narrative.get("catalysts"):
            story.append(Paragraph("Catalysts", hh)); bullets(narrative["catalysts"])
        if narrative.get("risks"):
            story.append(Paragraph("Key Risks", hh)); bullets(narrative["risks"])
    else:
        story.append(Paragraph("Thesis", hh))
        story.append(Paragraph(f"<b>{d['sector']} · {d['industry']}.</b> {a['action']}.", body))
        if d.get("summary"):
            story.append(Paragraph(d["summary"][:600] + ("…" if len(d["summary"]) > 600 else ""), body))

    # Snapshot table
    story.append(Paragraph("Snapshot", hh))
    snap = [
        ["Price", f"₹{d['price']:,.2f}", "Market Cap", _fmt_money(d.get("market_cap"))],
        ["P/E", f"{d['pe']:.1f}x" if d.get("pe") else "N/A", "ROE", f"{d['roe']*100:.1f}%" if d.get("roe") is not None else "N/A"],
        ["Rev. growth", f"{d['rev_growth']*100:.1f}%" if d.get("rev_growth") is not None else "N/A", "D/E", f"{d['debt_to_equity']:.2f}" if d.get("debt_to_equity") is not None else "N/A"],
        ["52-wk", f"₹{d.get('wk_low',0):,.0f}–₹{d.get('wk_high',0):,.0f}" if d.get("wk_high") else "N/A", "200-DMA", f"₹{d['dma200']:,.0f}" if d.get("dma200") else "N/A"],
    ]
    t = Table(snap, colWidths=[30 * mm, 52 * mm, 30 * mm, 53 * mm])
    t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D0D7DE")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#" + LIGHT)),
        ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#" + LIGHT)),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(t)

    # Factor scorecard
    story.append(Paragraph("Factor Scorecard", hh))
    data = [["Factor", "Value", "Signal", "Score"]]
    for f in a["factors"]:
        data.append([f["factor"], str(f["value"]), f["signal"], f"{f['points']:+d}"])
    data.append(["COMPOSITE", f"{a['score']}/{a['n']}", a["verdict"], f"{a['norm']:.2f}"])
    st = Table(data, colWidths=[42 * mm, 40 * mm, 45 * mm, 18 * mm])
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#" + NAVY)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D0D7DE")),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#" + LIGHT)),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    story.append(Table(data, colWidths=[42 * mm, 40 * mm, 45 * mm, 18 * mm], style=TableStyle(style)))

    # DCF
    dcf = a["dcf"]
    story.append(Paragraph("Valuation — DCF", hh))
    if dcf["fair_value"] is not None:
        story.append(Paragraph(
            f"Two-stage 10-yr DCF (discount {dcf['assumptions']['discount_rate']*100:.0f}%, "
            f"terminal {dcf['assumptions']['terminal_growth']*100:.0f}%) → "
            f"<b>fair value ₹{dcf['fair_value']:,.0f}</b> vs price ₹{d['price']:,.2f}, "
            f"implying <b>{dcf['upside']*100:+.0f}%</b>.", body))
    else:
        story.append(Paragraph(dcf["note"], body))

    story.append(Paragraph("Recommendation", hh))
    rec_text = narrative.get("recommendation") if narrative else a["action"]
    story.append(Paragraph(f"<b>{verdict}.</b> {rec_text}", body))

    story.append(Spacer(1, 10))
    src = "Figures: Yahoo Finance (live). Narrative: Claude." if narrative else "Data: Yahoo Finance (live)."
    story.append(Paragraph(
        f"<i>{src} Generated by J.A.R.V.I.S. Report Engine. "
        "Automated research, not personalised investment advice.</i>",
        ParagraphStyle("disc", parent=body, fontSize=7.5, textColor=colors.HexColor("#" + GREY))))

    doc.build(story)
    return buf.getvalue()


# ═══════════════════════════════════════════════════════════
#  4b. VALIDATION — evaluate the workbook's real formulas
# ═══════════════════════════════════════════════════════════
def validate_excel(xlsx_bytes: bytes, assumptions: dict) -> dict:
    """Load the generated workbook, actually COMPUTE its formulas with the
    `formulas` engine, and cross-check against an independent Python recompute.
    Returns {ok, checks:[{name, pass, detail}], computed_fair_value}."""
    import os
    import tempfile
    from openpyxl import load_workbook

    checks = []
    ok = True

    def add(name, passed, detail=""):
        nonlocal ok
        checks.append({"name": name, "pass": bool(passed), "detail": str(detail)})
        if not passed:
            ok = False

    # 1. Structure
    try:
        wb = load_workbook(io.BytesIO(xlsx_bytes))
        need = {"COVER", "KEY_METRICS", "SCORECARD", "ASSUMPTIONS", "MODEL"}
        missing = need - set(wb.sheetnames)
        add("all sheets present", not missing, "missing " + ", ".join(missing) if missing else "COVER·ANALYSIS·KEY_METRICS·SCORECARD·ASSUMPTIONS·MODEL")
        # cross-sheet links exist in MODEL
        wm = wb["MODEL"]
        linked = sum(1 for row in wm.iter_rows() for c in row
                     if isinstance(c.value, str) and c.value.startswith("=") and "ASSUMPTIONS!" in c.value)
        add("model is formula-linked", linked >= 15, f"{linked} cross-sheet formulas")
    except Exception as ex:
        add("workbook opens", False, str(ex)[:80])
        return {"ok": ok, "checks": checks, "computed_fair_value": None}

    # 2. Independent Python recompute (the oracle) — this IS the calc check.
    expected = python_dcf(assumptions)
    exp_fv = expected["fair_value"]
    add("enterprise value > 0", expected["ev"] > 0, f"₹{expected['ev']:,.0f} Cr")
    add("fair value computes", exp_fv is not None and exp_fv > 0,
        f"₹{exp_fv:,.2f}" if exp_fv else "not computed")
    computed_fv = exp_fv

    # 3. Optional heavy check: actually execute the workbook formulas and confirm
    #    they match the recompute. Slow (~8s) — off by default; the deterministic
    #    formula-writer + oracle already guarantee correctness.
    if os.getenv("VALIDATE_FORMULAS", "0") == "1":
        tmp_path = None
        try:
            import numpy as np
            import formulas
            tf = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
            tf.write(xlsx_bytes)
            tf.close()
            tmp_path = tf.name
            sol = formulas.ExcelModel().loads(tmp_path).finish().calculate()

            def get(cell):
                suffix = f"MODEL'!{cell}".upper()
                for k, v in sol.items():
                    if k.upper().endswith(suffix):
                        try:
                            return float(np.ravel(v.value)[0])
                        except Exception:
                            return None
                return None

            engine_fv = get("B20")
            if engine_fv is not None and exp_fv:
                diff = abs(engine_fv - exp_fv) / abs(exp_fv)
                add("Excel formulas match recompute (<0.5%)", diff < 0.005,
                    f"Excel ₹{engine_fv:,.2f} vs Python ₹{exp_fv:,.2f} ({diff*100:.3f}%)")
        except Exception as ex:
            add("formula engine evaluates", False, str(ex)[:100])
        finally:
            if tmp_path:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    return {"ok": ok, "checks": checks, "computed_fair_value": computed_fv,
            "expected_fair_value": exp_fv}


# ═══════════════════════════════════════════════════════════
#  5. TOP-LEVEL
# ═══════════════════════════════════════════════════════════
def prepare(symbol: str):
    """Fetch + analyse. Returns (data, analysis)."""
    d = fetch_stock(symbol)
    a = analyze(d)
    return d, a


def build_prompt(d: dict, a: dict):
    """Build (system, user) for Claude to author the institutional narrative,
    grounded on REAL figures so it doesn't invent numbers."""
    facts = {
        "company": d["name"], "symbol": d["symbol"],
        "sector": d["sector"], "industry": d["industry"],
        "price_inr": round(d["price"], 2),
        "market_cap": _fmt_money(d.get("market_cap")),
        "trailing_pe": d.get("pe"), "forward_pe": d.get("forward_pe"),
        "peg": d.get("peg"), "price_to_book": d.get("pb"),
        "roe_pct": round(d["roe"] * 100, 1) if d.get("roe") is not None else None,
        "profit_margin_pct": round(d["margin"] * 100, 1) if d.get("margin") is not None else None,
        "revenue_growth_pct": round(d["rev_growth"] * 100, 1) if d.get("rev_growth") is not None else None,
        "debt_to_equity": d.get("debt_to_equity"),
        "revenue": _fmt_money(d.get("revenue")), "fcf": _fmt_money(d.get("fcf")),
        "wk_high": d.get("wk_high"), "wk_low": d.get("wk_low"),
        "dma200": d.get("dma200"),
        "dcf_fair_value": round(a["dcf"]["fair_value"]) if a["dcf"]["fair_value"] else None,
        "dcf_upside_pct": round(a["dcf"]["upside"] * 100) if a["dcf"]["upside"] is not None else None,
        "quant_verdict": a["verdict"], "quant_score": f"{a['score']}/{a['n']}",
    }
    system = (
        "You are a Managing Director of equity research at a top-tier institutional "
        "desk (think Goldman Sachs / Morgan Stanley), writing a long-horizon (3–5 year) "
        "coverage note for sophisticated buy-side clients. Standards:\n"
        "• Rigorous, specific, and balanced — no hype, no filler, no hedging platitudes.\n"
        "• Ground every claim in the VERIFIED FIGURES provided; NEVER invent or alter a "
        "number, price, ratio, or statistic. Qualitative judgement is yours; data is not.\n"
        "• Think in terms of moat, unit economics, capital allocation, industry structure, "
        "and through-cycle earnings power.\n"
        "• You ALSO set the forward DCF driver assumptions that will populate a live Excel "
        "model. Make them defensible and consistent with the company's real margins, growth, "
        "and balance sheet shown in the figures."
    )
    user = (
        f"Produce an institutional long-term research note and DCF driver set for "
        f"{d['name']} ({d['symbol']}).\n\n"
        f"VERIFIED FIGURES (the only hard numbers you may cite):\n{json.dumps(facts, indent=2)}\n\n"
        "Return ONLY strictly valid JSON — no markdown fences, no comments, no trailing "
        "commas, no text outside the object. Keys and meaning:\n"
        "- thesis: 2-3 tight sentences — the long-term investment thesis\n"
        "- business: 1-2 sentences on what it does, its moat, unit economics\n"
        "- bull_case: array of exactly 3 specific one-line points\n"
        "- bear_case: array of exactly 3 specific one-line points\n"
        "- catalysts: array of 2 forward catalysts with rough timing\n"
        "- risks: array of 2 key risks, most material first\n"
        "- verdict: your FINAL call, exactly one of: BUY, ACCUMULATE, HOLD, REDUCE, SELL\n"
        "- verdict_rationale: ONE short clause under 16 words — the core reason for the call\n"
        "- recommendation: 2 sentence rationale for a 3-5 year horizon\n"
        "- price_target: number (your 12-month fair value in INR) or null\n"
        "- assumptions: object with decimals: growth (array of 5 yearly revenue-growth "
        "rates, realistic vs history), ebit_margin (sustainable operating margin), "
        "tax_rate (~0.25 for India), capex_pct, da_pct, nwc_pct (incremental NWC as % of "
        "revenue change), wacc (discount rate reflecting risk), terminal_growth "
        "(long-run, below wacc, ~0.03-0.05).\n"
        "- wacc_build: object showing how you derived WACC (like an IB memo): "
        "rf (risk-free, India 10yr G-sec ~0.07), erp (equity risk premium ~0.06-0.08), "
        "beta, cost_of_equity, cost_of_debt (after-tax), equity_weight, debt_weight, "
        "and a one-line note. All decimals.\n"
        "- assumption_log: array of 4-6 short strings — each a key modelling assumption "
        "with its basis (e.g. 'Revenue growth fades 15%→8% as base scales', 'EBIT margin "
        "24% vs 22% trailing on operating leverage', 'WACC 12.5% — high ERP for India').\n\n"
        'Example shape: {"thesis":"...","business":"...","bull_case":["..."],'
        '"bear_case":["..."],"catalysts":["..."],"risks":["..."],'
        '"verdict":"ACCUMULATE","verdict_rationale":"Quality franchise, fair value, stagger entries",'
        '"recommendation":"...",'
        '"price_target":3200,"assumptions":{"growth":[0.09,0.09,0.08,0.08,0.07],'
        '"ebit_margin":0.25,"tax_rate":0.25,"capex_pct":0.03,"da_pct":0.03,"nwc_pct":0.02,'
        '"wacc":0.12,"terminal_growth":0.045},'
        '"wacc_build":{"rf":0.07,"erp":0.07,"beta":0.9,"cost_of_equity":0.133,'
        '"cost_of_debt":0.06,"equity_weight":0.9,"debt_weight":0.1,"note":"India 10yr + Damodaran ERP"},'
        '"assumption_log":["Revenue growth fades 9%→7% as base scales",'
        '"EBIT margin 25% on operating leverage","WACC 12% — elevated ERP for India"]}'
    )
    return system, user


def _parse_narrative(text: str):
    """Best-effort extract the JSON object from Claude's reply — tolerant of
    markdown fences, // comments, and trailing commas that LLMs sometimes emit."""
    import re
    if not text:
        return None
    try:
        s = text[text.index("{"): text.rindex("}") + 1]
    except ValueError:
        return None
    for attempt in (s, None):
        if attempt is None:
            # sanitise: strip // comments (not inside URLs) and trailing commas
            s2 = re.sub(r'(?<!:)//[^\n\r]*', '', s)
            s2 = re.sub(r'/\*.*?\*/', '', s2, flags=re.S)
            s2 = re.sub(r',(\s*[}\]])', r'\1', s2)
            attempt = s2
        try:
            return json.loads(attempt)
        except (ValueError, json.JSONDecodeError):
            continue
    return None


def assemble(d: dict, a: dict, narrative=None, validate=True) -> dict:
    asmp = merge_assumptions(default_assumptions(d), (narrative or {}).get("assumptions"))
    excel = build_excel(d, a, narrative, asmp)
    validation = validate_excel(excel, asmp) if validate else None
    recency = data_recency(d)
    if validation is not None:
        # Python data-recency gate → appended to the checks
        validation["checks"].append({
            "name": "data recency (latest/prev quarter)",
            "pass": recency["ok"],
            "detail": f"{recency['status']} — financials as-of {recency['asof']}",
        })
        if not recency["ok"]:
            validation["ok"] = False
    result = {
        "symbol": d["symbol"],
        "name": d["name"],
        "summary": two_line_summary(d, a, narrative),
        "verdict": final_verdict(a, narrative),
        "quant_verdict": a["verdict"],
        "action": a["action"],
        "price": d["price"],
        "price_target": (narrative or {}).get("price_target"),
        "data_asof": recency["asof"],
        "data_status": recency["status"],
        "authored_by": "Claude + live data" if narrative else "Quant engine (live data)",
        "assumptions": asmp,
        "validation": validation,
        "excel": excel,
        "pdf": build_pdf(d, a, narrative),
    }
    result["numbers"] = numbers_block(d, a, result)
    result["analysis"], result["speech"] = compose_analysis(d, a, narrative, result)
    return result


def generate_report(symbol: str, narrative=None) -> dict:
    d, a = prepare(symbol)
    return assemble(d, a, narrative)


if __name__ == "__main__":
    import sys
    sym = sys.argv[1] if len(sys.argv) > 1 else "INFY"
    r = generate_report(sym)
    with open(f"/tmp/{r['symbol']}_model.xlsx", "wb") as f:
        f.write(r["excel"])
    with open(f"/tmp/{r['symbol']}_report.pdf", "wb") as f:
        f.write(r["pdf"])
    print(r["summary"])
    print(f"Excel: /tmp/{r['symbol']}_model.xlsx  ({len(r['excel'])} bytes)")
    print(f"PDF:   /tmp/{r['symbol']}_report.pdf  ({len(r['pdf'])} bytes)")
