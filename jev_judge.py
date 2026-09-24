"""Jev (TypeSafe System One) as JARVIS's final decision-maker.

Jev reads the assembled evidence — the rule scorecard, the DCF, street
consensus and Claude's narrative — and returns a calibrated probability
distribution over BUY / ACCUMULATE / HOLD / REDUCE / SELL. The top option is
the final verdict. The distribution gives a credible interval on the call.

Runs on Python 3.9 (the JARVIS server), so this talks to the HTTP API with
urllib instead of the typesafe-sdk (which needs 3.10+).

Interval semantics: the "80% interval" is a CREDIBLE interval taken from the
probability distribution Jev returns for one call (the central 80% of the
mass on the ordered scale). It is not a sampling interval from repeated
runs; Jev returns the same distribution for the same state.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

API_URL = "https://api.typesafe.ai/v1/systemone"
MODEL = os.environ.get("JEV_MODEL", "jev-latest")
TIMEOUT = float(os.environ.get("JEV_TIMEOUT", "40"))
INTERVAL_MASS = 0.80

# Ordered worst → best. Index - 2 gives a stance from -2 (SELL) to +2 (BUY).
VERDICTS = ["SELL", "REDUCE", "HOLD", "ACCUMULATE", "BUY"]

ACTION_TEXT = {
    "BUY": "Accumulate on dips — strong long-term conviction",
    "ACCUMULATE": "Build position gradually via SIP/DCA",
    "HOLD": "Hold existing; await better entry or catalysts",
    "REDUCE": "Trim on strength; risks outweigh reward",
    "SELL": "Exit; evidence shows unfavourable risk/reward",
}

VALUATION_LEVELS = [
    "Clearly expensive: the price sits well above DCF fair value and the multiples are rich for the growth on offer.",
    "Fully valued: the price is near fair value with little margin of safety.",
    "Modestly cheap: some upside to fair value and multiples that are acceptable for the growth.",
    "Clearly undervalued: large upside to fair value and multiples that are cheap for the growth on offer.",
]
RISK_LEVELS = [
    "Low: strong balance sheet, stable earnings, few named risks.",
    "Moderate: some named risks or leverage, manageable over the horizon.",
    "Elevated: material named risks, a weak price trend or a stretched valuation that could drive a large drawdown.",
    "Severe: several serious risks at once; a large permanent loss is plausible.",
]
VALUATION_SHORT = ["expensive", "fully valued", "modestly cheap", "undervalued"]
RISK_SHORT = ["low", "moderate", "elevated", "severe"]


def _load_env():
    if os.environ.get("TYPESAFE_API_KEY"):
        return
    env = Path(__file__).with_name(".env")
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def available() -> bool:
    _load_env()
    return bool(os.environ.get("TYPESAFE_API_KEY"))


# ─────────────────────────── state ───────────────────────────

MAX_STATE_CHARS = 90_000   # Jev takes 32k tokens of state; stay well inside

def _narrative_state(n: dict) -> dict:
    """Everything Claude wrote, minus nothing: thesis, cases, scenarios, comps,
    SOTP, assumptions, WACC build, assumption log, sources, levels."""
    return {k: v for k, v in n.items() if v not in (None, "", [], {})}


def _clean(v):
    """JSON-safe copy: drop None/empty, round floats, keep everything else."""
    if isinstance(v, dict):
        return {k: _clean(x) for k, x in v.items() if x not in (None, "", [], {})}
    if isinstance(v, (list, tuple)):
        return [_clean(x) for x in v]
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, float):
        if v != v or v in (float("inf"), float("-inf")):
            return None
        return round(v, 4)
    if isinstance(v, (int, str)):
        return v
    return str(v)   # dates, Decimals, numpy scalars, anything else


def build_state(d: dict, a: dict, narrative, horizon: str, dcf_fair_value=None,
                dcf_detail=None, triangulation=None, data_quality=None) -> dict:
    price = d["price"]
    metric_keys = ("pe", "forward_pe", "peg", "pb", "roe", "margin", "rev_growth",
                   "earn_growth", "debt_to_equity", "div_yield", "beta",
                   "wk_high", "wk_low", "dma50", "dma200", "market_cap", "revenue", "fcf",
                   "op_cf", "net_income", "total_debt", "total_cash", "shares",
                   "rev_cagr", "rev_hist_cr", "fy_base", "quarter_end", "data_ref_date",
                   "price_note", "currency", "fin_ccy")
    state = {
        "company": d.get("name"),
        "symbol": d.get("symbol"),
        "sector": d.get("sector"),
        "industry": d.get("industry"),
        "business_summary": (d.get("summary") or "")[:3000] or None,
        "horizon": ("6-12 month trade, judged on technicals" if horizon == "short"
                    else "3-5 year investment, judged on fundamentals and DCF"),
        "current_price_inr": price,
        "key_metrics": {k: d.get(k) for k in metric_keys if d.get(k) is not None},
        "technicals": _clean(d.get("tech") or {}) or None,
        "rule_scorecard": {
            "factors": [{"factor": f["factor"], "value": f["value"], "signal": f["signal"],
                         "points": f["points"]} for f in a.get("factors", [])],
            "composite": f"{a.get('score')}/{a.get('n')}",
            "rule_verdict": a.get("verdict"),
        },
    }
    fv = dcf_fair_value or (a.get("dcf") or {}).get("fair_value")
    if fv:
        state["dcf"] = {"fair_value_inr": round(fv, 2),
                        "upside_pct": round((fv / price - 1) * 100, 1)}
        if dcf_detail:
            # full model: assumptions, WACC, year-by-year schedule, EV bridge
            state["dcf"].update(_clean(dcf_detail))
    rule_dcf = a.get("dcf") or {}
    if rule_dcf.get("fair_value") and (not fv or abs(rule_dcf["fair_value"] - fv) > 1):
        state["rule_based_dcf"] = _clean(rule_dcf)
    if triangulation:
        # every valuation method JARVIS ran, side by side, each with its upside vs price
        state["valuation_triangulation"] = {
            "note": "Each method's fair value per share and its gap to the current price. "
                    "Weigh them together; no single method is the answer.",
            "methods": _clean(triangulation)}
    if data_quality:
        state["data_quality"] = _clean(data_quality)
    tm = d.get("target_mean")
    if tm and 0.3 * price <= tm <= 3 * price:
        state["street_consensus"] = {
            "recommendation": (d.get("rec_key") or "").upper().replace("_", " ") or None,
            "recommendation_mean_1_to_5": d.get("rec_mean"),
            "mean_target_inr": tm, "high": d.get("target_high"), "low": d.get("target_low"),
            "num_analysts": int(d["num_analysts"]) if d.get("num_analysts") else None,
            "implied_upside_pct": round((tm / price - 1) * 100, 1),
            "rating_distribution": d.get("rating_dist"),
            "recent_broker_actions": (d.get("brokers") or [])[:12],
        }
    state["analyst_narrative"] = _narrative_state(narrative) if narrative else None
    state = _clean(state)
    # bound the payload: trim the longest free-text fields first, never the numbers
    for k in ("business_summary",):
        while len(json.dumps(state)) > MAX_STATE_CHARS and state.get(k):
            state[k] = state[k][: len(state[k]) // 2] or None
    if len(json.dumps(state)) > MAX_STATE_CHARS and state.get("analyst_narrative"):
        n = state["analyst_narrative"]
        for k in ("sources", "assumption_log", "comps", "sotp", "business"):
            n.pop(k, None)
            if len(json.dumps(state)) <= MAX_STATE_CHARS:
                break
    return state


# ─────────────────────────── questions ───────────────────────────

def build_questions(has_narrative: bool) -> dict:
    q = {
        "verdict": {
            "type": "choice",
            "instructions": (
                "You are the final decision-maker on an equity research desk. Read the whole "
                "state: the rule scorecard, every valuation method in `valuation_triangulation`, "
                "the DCF detail, the technicals, the street consensus, `data_quality` and the analyst "
                "narrative. Decide the call for the stated "
                "horizon at the current price. Weigh the numbers over the narrative's tone: a "
                "confident narrative that the scorecard and DCF do not support should not earn "
                "a BUY, and a cautious narrative over strong numbers should not earn a SELL. "
                "If `data_quality` flags stale financials or a failed price cross-check, lean "
                "toward HOLD rather than a strong call."
            ),
            "criteria": {
                "BUY": "Strong conviction. The evidence supports buying now at the current price and adding on dips.",
                "ACCUMULATE": "Favourable but not compelling at today's price. Build a position gradually in tranches rather than all at once.",
                "HOLD": "Hold what is owned; neither add nor sell. Risk and reward are balanced, or the evidence is mixed.",
                "REDUCE": "Trim on strength. Risks outweigh the reward at the current price, but the case is not bad enough to exit fully.",
                "SELL": "Exit the position. The evidence shows unfavourable risk/reward, deteriorating fundamentals, or a valuation the numbers do not support.",
            },
        },
        "valuation": {
            "type": "score",
            "instructions": ("How much does the valuation evidence support paying the current price? "
                             "Weigh EVERY method in `valuation_triangulation.methods` (DCF, peer comps, "
                             "sum-of-the-parts, the probability-weighted scenario target, the analyst's "
                             "own target, the street's mean and range) together with the multiples in "
                             "`key_metrics` (P/E, forward P/E, PEG, price/book). Methods that agree "
                             "count more than one outlier; a method's gap to price matters more than its label."),
            "criteria": VALUATION_LEVELS,
        },
        "downside_risk": {
            "type": "score",
            "instructions": "How large is the risk of a material loss over the stated horizon, judged "
                            "from leverage, earnings stability, price trend, valuation and the named risks?",
            "criteria": RISK_LEVELS,
        },
    }
    if has_narrative:
        q["numbers_back_verdict"] = {
            "type": "noul",
            "instructions": (
                "The figures in `rule_scorecard`, `dcf`, `technicals` and `street_consensus` "
                "justify the CALL stated in `analyst_narrative.verdict` at the current price. "
                "Answer no if the call is stronger or weaker than those figures justify."
            ),
        }
        q["thesis_consistent"] = {
            "type": "noul",
            "instructions": (
                "Every factual claim in `analyst_narrative.thesis`, `bull_case` and `bear_case` "
                "is consistent with the figures in `key_metrics`, `rule_scorecard`, `dcf` and "
                "`street_consensus`. Answer no if the narrative asserts something the figures "
                "contradict or do not contain."
            ),
        }
    return q


# ─────────────────────────── plain-English trail ───────────────────────────

def describe_state(state: dict) -> list:
    """What was sent to Jev, as sentences a non-technical reader can follow."""
    out = [f"The company: {state.get('company')} ({state.get('symbol')}), "
           f"{state.get('industry') or state.get('sector')}, at Rs {state.get('current_price_inr'):,.0f}.",
           f"The horizon: {state.get('horizon')}."]
    km = state.get("key_metrics") or {}
    bits = []
    if km.get("pe") is not None: bits.append(f"P/E {km['pe']:.0f}x")
    if km.get("roe") is not None: bits.append(f"ROE {km['roe']*100:.0f}%")
    if km.get("rev_growth") is not None: bits.append(f"revenue growth {km['rev_growth']*100:.1f}%")
    if km.get("debt_to_equity") is not None:
        de = km["debt_to_equity"]; bits.append(f"debt/equity {(de/100 if de > 5 else de):.2f}")
    if bits:
        out.append("The key numbers: " + ", ".join(bits) + ".")
    sc = state.get("rule_scorecard") or {}
    if sc.get("factors"):
        out.append(f"The rule scorecard: {len(sc['factors'])} factors, composite {sc.get('composite')}, "
                   f"rule verdict {sc.get('rule_verdict')}. Each factor is sent with its value and signal "
                   f"(e.g. {sc['factors'][0]['factor']}: {sc['factors'][0]['value']}, {sc['factors'][0]['signal']}).")
    if state.get("dcf"):
        dcf = state["dcf"]
        line = (f"The DCF: fair value Rs {dcf['fair_value_inr']:,.0f}, "
                f"{dcf['upside_pct']:+.0f}% versus the price")
        asmp = dcf.get("assumptions") or {}
        if asmp.get("wacc"):
            line += (f"; WACC {asmp['wacc']*100:.1f}%, terminal growth {asmp.get('terminal_growth', 0)*100:.1f}%"
                     f", plus the full 5-year revenue/EBIT/FCF schedule and the EV-to-equity bridge")
        out.append(line + ".")
    tri = (state.get("valuation_triangulation") or {}).get("methods") or []
    if tri:
        out.append("Every valuation method side by side: " + "; ".join(
            f"{m['method']} Rs {m['value_inr']:,.0f} ({m['upside_pct']:+.0f}%)" for m in tri
            if m.get("value_inr")) + ".")
    dq = state.get("data_quality")
    if dq:
        out.append(f"Data quality: financials {dq.get('financials_status')} (as of {dq.get('financials_asof')}); "
                   f"price cross-check {'passed' if dq.get('price_check_ok') else 'FAILED'}"
                   + (f" ({dq['price_check_detail']})" if dq.get("price_check_detail") else "") + ".")
    if state.get("technicals"):
        tech = state["technicals"]
        out.append("The technicals: " + ", ".join(f"{k} {v}" for k, v in list(tech.items())[:8]) + ".")
    if state.get("business_summary"):
        out.append("The company's business description (from the exchange listing data).")
    cs = state.get("street_consensus")
    if cs:
        out.append(f"The street: {cs.get('recommendation') or 'n/a'}, mean target Rs {cs['mean_target_inr']:,.0f} "
                   f"({cs['implied_upside_pct']:+.0f}%), {int(cs['num_analysts']) if cs.get('num_analysts') else '?'} analysts.")
    n = state.get("analyst_narrative")
    if n:
        out.append(f"Claude's narrative: verdict {n.get('verdict')}"
                   + (f" ({n.get('verdict_rationale')})" if n.get("verdict_rationale") else "")
                   + f"; thesis: {str(n.get('thesis',''))[:160]}"
                   + ("…" if len(str(n.get("thesis", ""))) > 160 else "")
                   + f". Also sent: {len(n.get('bull_case') or [])} bull points, "
                   f"{len(n.get('bear_case') or [])} bear points, {len(n.get('risks') or [])} risks, "
                   f"{len(n.get('catalysts') or [])} catalysts"
                   + (f", price target Rs {n['price_target']:,.0f}" if n.get("price_target") else "")
                   + (", bull/base/bear scenarios" if n.get("scenarios") else "")
                   + (", peer comps" if n.get("comps") else "")
                   + (", sum-of-the-parts" if n.get("sotp") else "")
                   + (", the DCF assumptions, WACC build and assumption log" if n.get("assumptions") else "")
                   + (", and the street-versus-us commentary" if n.get("vs_consensus") else "") + ".")
    else:
        out.append("No Claude narrative was sent (numbers only).")
    return out


def describe_questions(q: dict) -> list:
    out = ["Question 1 (a choice): pick the final call, one of SELL, REDUCE, HOLD, ACCUMULATE, BUY, "
           "weighing the numbers over the narrative's tone. Jev returns a probability for each option.",
           "Question 2 (a 0–3 score): how much the valuation supports paying today's price, weighing "
           "every method together: DCF, peer comps, sum-of-the-parts, scenario-weighted target, "
           "analyst target, street mean and range, plus the multiples "
           "(expensive / fully valued / modestly cheap / undervalued).",
           "Question 3 (a 0–3 score): how large the risk of a material loss is over the horizon "
           "(low / moderate / elevated / severe)."]
    if "numbers_back_verdict" in q:
        out.append("Question 4 (yes/no probability): do the figures justify Claude's call at this price?")
        out.append("Question 5 (yes/no probability): is every claim in Claude's thesis consistent with the figures?")
    return out


def describe_answer(j: dict) -> list:
    lo, hi = j["interval"]
    out = [f"Jev's call: {j['verdict']} at {j['probabilities'][j['verdict']]*100:.0f}% probability, "
           f"confidence {j['confidence']:.2f} ({j['conviction']}).",
           f"The full spread: {distribution_line(j)}.",
           f"The 80% interval: " + (f"{lo} to {hi}" if lo != hi else f"{lo} alone") +
           " (the range that holds 80% of Jev's probability).",
           f"Valuation {j['valuation']['score']:.1f}/3 ({j['valuation']['label']}); "
           f"downside risk {j['downside_risk']['score']:.1f}/3 ({j['downside_risk']['label']})."]
    if j.get("numbers_back_verdict") is not None:
        out.append(f"Do the figures justify Claude's call? {j['numbers_back_verdict']*100:.0f}% yes.")
    if j.get("thesis_consistent") is not None:
        out.append(f"Is the thesis consistent with the figures? {j['thesis_consistent']*100:.0f}% yes.")
    if j.get("method_check"):
        out.append(j["method_check"])
    if j.get("sizing"):
        out.append(j["sizing"])
    return out


def feedback_for_claude(j: dict, claude_verdict) -> str:
    """The feedback paragraph Claude receives after a Jev round."""
    lo, hi = j["interval"]
    lines = []
    if j.get("method_check"):
        lines.append(j["method_check"])
    lines += [
        f"Jev (an independent calibrated judge) read your narrative together with the scorecard, DCF and consensus.",
        f"Jev's verdict: {j['verdict']} ({j['probabilities'][j['verdict']]*100:.0f}%), confidence {j['confidence']:.2f}, "
        f"80% interval {lo} to {hi}. Full distribution: {distribution_line(j)}.",
        f"Valuation support: {j['valuation']['score']:.1f}/3 ({j['valuation']['label']}). "
        f"Downside risk: {j['downside_risk']['score']:.1f}/3 ({j['downside_risk']['label']}).",
    ]
    if j.get("numbers_back_verdict") is not None:
        lines.append(f"Probability that the figures justify your call: {j['numbers_back_verdict']*100:.0f}%.")
    if j.get("thesis_consistent") is not None:
        lines.append(f"Probability that your thesis is consistent with the figures: {j['thesis_consistent']*100:.0f}%.")
    if claude_verdict and claude_verdict != j["verdict"]:
        lines.append(f"Your verdict was {claude_verdict}; Jev's is {j['verdict']}. Either reconcile your call with the "
                     f"numbers, or keep it and defend it with specific figures from the data.")
    else:
        lines.append("Jev agrees with your call. Tighten the thesis: remove any claim the figures do not support, "
                     "and make the strongest supported point first.")
    return "\n".join(lines)


# ─────────────────────────── maths ───────────────────────────

def credible_interval(ordered, mass=INTERVAL_MASS):
    """ordered: list of (label, probability) from worst to best.
    Returns (low_label, high_label) bounding the central `mass` of probability."""
    lo_t = (1 - mass) / 2
    hi_t = 1 - lo_t
    cum = 0.0
    lo = hi = None
    for label, p in ordered:
        cum += p
        if lo is None and cum >= lo_t - 1e-9:
            lo = label
        if hi is None and cum >= hi_t - 1e-9:
            hi = label
            break
    if lo is None:
        lo = ordered[0][0]
    if hi is None:
        hi = ordered[-1][0]
    return lo, hi


def conviction(confidence: float) -> str:
    if confidence >= 0.70:
        return "high"
    if confidence >= 0.40:
        return "medium"
    return "low"


def _score_block(ans: dict, short_labels) -> dict:
    probs = ans.get("probabilities") or {}
    ordered = [(i, float(probs.get(str(i), 0.0))) for i in range(len(short_labels))]
    lo, hi = credible_interval(ordered)
    return {
        "score": round(float(ans.get("score", 0.0)), 2),
        "max": len(short_labels) - 1,
        "confidence": round(float(ans.get("confidence", 0.0)), 2),
        "interval": [lo, hi],
        "label": short_labels[min(len(short_labels) - 1, int(round(float(ans.get("score", 0.0)))))],
        "interval_labels": [short_labels[lo], short_labels[hi]],
        "probabilities": {str(i): round(p, 3) for i, p in ordered},
    }


def position_guidance(j: dict) -> str:
    """Turn the distribution into a sizing instruction. Stance is the expected
    position on the -2 (SELL) … +2 (BUY) scale; width is how many of the five
    calls the 80% interval spans (1 = decisive, 5 = evidence fully divided)."""
    st = j["stance"]
    lo, hi = j["interval"]
    width = VERDICTS.index(hi) - VERDICTS.index(lo) + 1
    if st >= 1.5:
        base = "Full position now; add on dips."
    elif st >= 0.5:
        base = "Build in two or three tranches over the next few weeks; do not chase."
    elif st > -0.5:
        base = "No new money. Hold what is owned; wait for a better entry or a catalyst."
    elif st > -1.5:
        base = "Trim into strength; cut the position by roughly a third to a half."
    else:
        base = "Exit; redeploy the capital."
    if width >= 3:
        base += (f" The 80% interval spans {width} of the five calls, so the evidence is divided: "
                 "halve the size of any action and revisit after the next results.")
    elif width == 2:
        base += " The interval spans two calls, so size at two-thirds of normal."
    return f"Sizing (stance {st:+.2f}): {base}"


def method_check(j: dict, triangulation) -> str:
    """Code-level cross-check: does Jev's call sit with the majority of the
    valuation methods? Returns a warning line, or a one-line agreement."""
    vals = [m for m in (triangulation or []) if m.get("value_inr") and m.get("upside_pct") is not None]
    if not vals:
        return ""
    above = [m["method"] for m in vals if m["upside_pct"] >= 10]
    below = [m["method"] for m in vals if m["upside_pct"] <= -10]
    n = len(vals)
    v = j["verdict"]
    bullish = v in ("BUY", "ACCUMULATE")
    bearish = v in ("REDUCE", "SELL")
    if bullish and len(below) > n / 2:
        return (f"Warning: {v} contradicts {len(below)} of {n} valuation methods, which sit 10%+ below "
                f"the price ({', '.join(below)}).")
    if bearish and len(above) > n / 2:
        return (f"Warning: {v} contradicts {len(above)} of {n} valuation methods, which sit 10%+ above "
                f"the price ({', '.join(above)}).")
    return (f"Method check: {len(above)} of {n} methods 10%+ above price, {len(below)} of {n} 10%+ below; "
            f"the {v} call is consistent with the majority.")


def log_decision(record: dict, path=None):
    """Append the final decision to a JSONL log so calibration can be checked
    against later prices (tools/jev_calibration.py). Never raises."""
    try:
        path = Path(path) if path else Path(__file__).with_name("data") / "jev_decisions.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as fh:
            fh.write(json.dumps(record, default=str) + "\n")
    except Exception as exc:
        print(f"[jev] log failed: {exc}", file=sys.stderr)


# ─────────────────────────── call ───────────────────────────

def _post(payload: dict) -> dict:
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        API_URL, data=body, method="POST",
        headers={"Authorization": f"Bearer {os.environ['TYPESAFE_API_KEY']}",
                 "Content-Type": "application/json"})
    delay = 1.0
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code in (429, 529) and attempt < 3:
                time.sleep(delay)
                delay *= 2
                continue
            detail = e.read().decode(errors="replace")[:300]
            raise RuntimeError(f"Jev HTTP {e.code}: {detail}")
    raise RuntimeError("Jev: retries exhausted")


def judge(d: dict, a: dict, narrative=None, horizon="long", dcf_fair_value=None, dcf_detail=None,
          triangulation=None, data_quality=None):
    """Return Jev's decision dict, or None when Jev is unavailable or errors.
    Never raises: a Jev outage must not take the report down."""
    if not available():
        return None
    try:
        state = build_state(d, a, narrative, horizon, dcf_fair_value, dcf_detail,
                            triangulation, data_quality)
        questions = build_questions(bool(narrative))
        r = _post({"model": MODEL, "state": state, "questions": questions})
        ans = r["answers"]
        v = ans["verdict"]
        probs = {k: float(v["probabilities"].get(k, 0.0)) for k in VERDICTS}
        ordered = [(k, probs[k]) for k in VERDICTS]
        lo, hi = credible_interval(ordered)
        stance = sum((i - 2) * p for i, (_, p) in enumerate(ordered))
        conf = float(v.get("confidence", 0.0))
        claude_v = (narrative or {}).get("verdict")
        claude_v = str(claude_v).upper() if claude_v else None
        out = {
            "verdict": v["choice"],
            "confidence": round(conf, 2),
            "conviction": conviction(conf),
            "probabilities": {k: round(p, 3) for k, p in probs.items()},
            "interval": [lo, hi],
            "interval_mass": INTERVAL_MASS,
            "stance": round(stance, 2),
            "valuation": _score_block(ans["valuation"], VALUATION_SHORT),
            "downside_risk": _score_block(ans["downside_risk"], RISK_SHORT),
            "numbers_back_verdict": (round(float(ans["numbers_back_verdict"]["noul"]), 2)
                                     if "numbers_back_verdict" in ans else None),
            "thesis_consistent": (round(float(ans["thesis_consistent"]["noul"]), 2)
                                  if "thesis_consistent" in ans else None),
            "agreement": {"claude": claude_v, "quant": a.get("verdict")},
            "model": r.get("model"),
            "input_tokens": (r.get("usage") or {}).get("input_tokens"),
            "sent": describe_state(state),
            "asked": describe_questions(questions),
        }
        out["sizing"] = position_guidance(out)
        out["method_check"] = method_check(out, triangulation)
        out["triangulation"] = _clean(triangulation) if triangulation else None
        out["received"] = describe_answer(out)
        return out
    except Exception as exc:  # network, key, schema — degrade to the old verdict chain
        print(f"[jev] unavailable: {type(exc).__name__}: {exc}", file=sys.stderr)
        return None


# ─────────────────────────── presentation ───────────────────────────

def distribution_line(j: dict) -> str:
    return " · ".join(f"{k} {j['probabilities'][k]*100:.0f}%" for k in reversed(VERDICTS))


def summary_line(j: dict) -> str:
    lo, hi = j["interval"]
    rng = f"{lo} to {hi}" if lo != hi else lo
    return (f"Jev: **{j['verdict']}** {j['probabilities'][j['verdict']]*100:.0f}% · "
            f"confidence {j['confidence']:.2f} ({j['conviction']}) · "
            f"{int(j['interval_mass']*100)}% interval {rng}")


def support_line(j: dict) -> str:
    val, risk = j["valuation"], j["downside_risk"]
    parts = [f"Valuation {val['score']:.1f}/{val['max']} ({val['label']}; "
             f"80% interval {val['interval'][0]}–{val['interval'][1]})",
             f"Downside risk {risk['score']:.1f}/{risk['max']} ({risk['label']}; "
             f"80% interval {risk['interval'][0]}–{risk['interval'][1]})"]
    if j.get("numbers_back_verdict") is not None:
        parts.append(f"Numbers back Claude's call: {j['numbers_back_verdict']*100:.0f}%")
    if j.get("thesis_consistent") is not None:
        parts.append(f"Thesis consistent with the figures: {j['thesis_consistent']*100:.0f}%")
    return " · ".join(parts)


def agreement_line(j: dict) -> str:
    ag = j["agreement"]
    bits = []
    if ag.get("claude"):
        bits.append(f"Claude's call {ag['claude']}")
    if ag.get("quant"):
        bits.append(f"quant scorecard {ag['quant']}")
    return "Inputs: " + " · ".join(bits) if bits else ""


def speech_fragment(j: dict) -> str:
    lo, hi = j["interval"]
    rng = f"{lo.lower()} to {hi.lower()}" if lo != hi else f"{lo.lower()} alone"
    return (f"Jev confidence {j['confidence']*100:.0f} percent, "
            f"eighty percent interval {rng}.")


if __name__ == "__main__":
    import report_engine as R
    sym = sys.argv[1] if len(sys.argv) > 1 else "INFY"
    d, a = R.prepare(sym)
    j = judge(d, a, None, "long")
    print(json.dumps(j, indent=2))
    if j:
        print(summary_line(j))
        print(distribution_line(j))
        print(support_line(j))
        print(speech_fragment(j))
