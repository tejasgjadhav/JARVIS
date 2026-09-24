"""Build the non-technical workflow PDF: block diagrams of how JARVIS, Claude
and Jev reach a final buy/sell/accumulate call, plus a worked example taken
from a real /api/stock/report response (JSON file passed as argv[1]).

Usage: python3 tools/jev_workflow_pdf.py eternal.json ~/Downloads/JARVIS_Jev_Workflow.pdf
"""
import html
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

src = Path(sys.argv[1])
out = Path(sys.argv[2]).expanduser()
r = json.loads(src.read_text())
j = r.get("jev") or {}
trail = r.get("jev_trail") or []
E = html.escape


def box(title, body="", cls=""):
    return (f'<div class="box {cls}"><div class="bt">{E(title)}</div>'
            + (f'<div class="bb">{E(body)}</div>' if body else "") + "</div>")


ARROW = '<div class="arrow">&#8595;</div>'
ARROW_R = '<div class="arrow-r">&#8594;</div>'

# ── Page 1: the whole pipeline as blocks ──
pipeline = "".join([
    box("1. You ask", 'Say or type: "should I buy Eternal?"', "you"), ARROW,
    box("2. JARVIS fetches live numbers", "Price, P/E, growth, margins, debt, cash flow, 52-week range, moving averages, analyst targets"), ARROW,
    box("3. Rule scorecard", "Seven fixed rules score the numbers. Gives a first, mechanical call."), ARROW,
    box("4. Claude writes the analysis", "Thesis, bull and bear case, risks, catalysts, DCF assumptions, a price target, and its own verdict", "claude"), ARROW,
    box("5. JARVIS triangulates the value", "Six methods side by side: DCF from Claude's assumptions (never bent toward the market price), peer comps, sum-of-the-parts, probability-weighted scenarios, Claude's target, the street's mean and range. Plus a data-quality check: how fresh the financials are and whether a second source agrees on the price."), ARROW,
    box("6. Jev judges (round 1)", "Reads everything from steps 2 to 5. Returns a probability for each of SELL, REDUCE, HOLD, ACCUMULATE, BUY, plus valuation and risk scores and two checks on Claude's note", "jev"), ARROW,
    box("7. Claude gets Jev's feedback", "Sees Jev's probabilities and scores. Revises its analysis. Must keep every number grounded.", "claude"), ARROW,
    box("8. Jev judges again (round 2)", "Reads the revised analysis with the same numbers. Its answer is the FINAL call.", "jev"), ARROW,
    box("9. Code cross-checks and sizes", "JARVIS checks Jev's call against the majority of the six valuation methods (warns if they contradict), flags a revision that looks written to please the judge, and turns the probability spread into a position size."), ARROW,
    box("10. You get the decision, and it is logged", "Chat, spoken summary, Excel model, PDF note. Each shows the call, the confidence, the 80% interval, the sizing and the step-by-step trail. Every decision is logged so its calibration can be checked against later prices.", "you"),
])

# ── Page 2: who does what ──
roles = f'''
<div class="row3">
  {box("JARVIS (the code)", "Fetches data. Runs the rules. Builds the DCF and the Excel. Sends the evidence to Claude and Jev. Assembles the report. It never guesses.", "code")}
  {box("Claude (the writer)", "Reads the numbers and writes the research note the way an analyst would. Proposes a verdict and a price target. Can be persuasive, so it is not the final word.", "claude")}
  {box("Jev (the judge)", "Reads the numbers AND Claude's note. Does not write. Returns probabilities: how likely each call is, given this evidence. Has no market data of its own, so it judges only what it is shown.", "jev")}
</div>'''

# ── Page 2b: what confidence and the interval mean ──
probs = j.get("probabilities") or {}
order = ["SELL", "REDUCE", "HOLD", "ACCUMULATE", "BUY"]
bars = "".join(
    f'<div class="bar"><div class="barlab">{k}</div><div class="bartrack"><div class="barfill" style="width:{probs.get(k,0)*100:.0f}%"></div></div><div class="barval">{probs.get(k,0)*100:.0f}%</div></div>'
    for k in order)
lo, hi = (j.get("interval") or ["?", "?"])
interval_txt = f"{lo} to {hi}" if lo != hi else f"{lo} alone"

tri = j.get("triangulation") or []
tri_table = ""
if tri:
    tri_table = ('<p><b>Every valuation method, side by side</b></p><table><tr><th>Method</th><th>Fair value (Rs)</th><th>Gap to price</th></tr>'
                 + "".join(f"<tr><td>{E(m['method'])}</td><td>{m['value_inr']:,.0f}</td><td>{m['upside_pct']:+.0f}%</td></tr>" for m in tri)
                 + "</table>")

# ── Page 3: the worked example trail ──
steps_html = ""
for st in trail:
    cls = "jev" if "Jev" in st["title"] and "Claude" not in st["title"] else ("claude" if "Claude" in st["title"] else "code")
    lines = "".join(f"<li>{E(l)}</li>" for l in st.get("lines", []))
    steps_html += f'<div class="step {cls}"><div class="st">Step {st["step"]}. {E(st["title"])}</div><ul>{lines}</ul></div>'

price = r.get("price") or 0
fv = r.get("fair_value")
tgt = r.get("price_target")

doc = f'''<!doctype html><html><head><meta charset="utf-8">
<style>
 @page {{ size: A4; margin: 14mm 14mm 16mm 14mm; }}
 body {{ font-family: -apple-system, "Helvetica Neue", Arial, sans-serif; color:#14213d; font-size:10.5pt; line-height:1.4; }}
 h1 {{ font-size:22pt; margin:0 0 4px 0; color:#0b1f3a; }}
 h2 {{ font-size:15pt; margin:0 0 8px 0; color:#0b1f3a; border-bottom:2px solid #00a8e8; padding-bottom:3px; }}
 .sub {{ color:#6b7a8d; font-size:9.5pt; margin-bottom:12px; }}
 .page {{ page-break-after: always; }}
 .box {{ border:1.5px solid #0b1f3a; border-radius:8px; padding:7px 10px; background:#f7fafc; margin:0 auto; width:86%; }}
 .box .bt {{ font-weight:700; font-size:11pt; }}
 .box .bb {{ font-size:9.5pt; color:#334155; margin-top:2px; }}
 .box.you {{ background:#fff7e6; border-color:#c77d00; }}
 .box.claude {{ background:#fdf0ea; border-color:#ce6440; }}
 .box.jev {{ background:#e8f3ff; border-color:#1b6fb3; }}
 .box.code {{ background:#f1f5f9; border-color:#475569; }}
 .arrow {{ text-align:center; font-size:16pt; line-height:1; color:#0b1f3a; margin:1px 0; }}
 .row3 {{ display:flex; gap:10px; margin:10px 0 14px 0; }}
 .row3 .box {{ width:auto; flex:1; margin:0; }}
 .bar {{ display:flex; align-items:center; gap:8px; margin:3px 0; }}
 .barlab {{ width:95px; font-weight:600; font-size:9.5pt; }}
 .bartrack {{ flex:1; height:14px; background:#e2e8f0; border-radius:4px; overflow:hidden; }}
 .barfill {{ height:100%; background:#1b6fb3; }}
 .barval {{ width:36px; text-align:right; font-size:9.5pt; }}
 .step {{ border-left:4px solid #475569; padding:4px 10px; margin:6px 0; background:#f8fafc; page-break-inside:avoid; }}
 .step.jev {{ border-color:#1b6fb3; background:#eef5fc; }}
 .step.claude {{ border-color:#ce6440; background:#fdf3ee; }}
 .step .st {{ font-weight:700; }}
 .step ul {{ margin:3px 0 2px 14px; padding:0; }}
 .step li {{ margin:1px 0; font-size:9.6pt; }}
 table {{ border-collapse:collapse; width:100%; font-size:9.8pt; margin:8px 0; }}
 th, td {{ border:1px solid #cbd5e1; padding:5px 7px; text-align:left; vertical-align:top; }}
 th {{ background:#0b1f3a; color:#fff; }}
 .kpi {{ display:flex; gap:10px; margin:8px 0; }}
 .kpi div {{ flex:1; border:1px solid #cbd5e1; border-radius:6px; padding:6px 8px; background:#fff; }}
 .kpi b {{ display:block; font-size:13pt; color:#0b1f3a; }}
 .note {{ background:#fffbeb; border:1px solid #f59e0b; border-radius:6px; padding:6px 10px; font-size:9.6pt; margin:8px 0; }}
</style></head><body>

<div class="page">
<h1>How JARVIS decides: buy, accumulate, hold, reduce or sell</h1>
<div class="sub">The full workflow with Claude as the writer and Jev as the judge · {date.today().strftime("%d %B %Y")}</div>
{pipeline}
</div>

<div class="page">
<h2>Who does what</h2>
{roles}
<h2>What the numbers from Jev mean</h2>
<p><b>Probabilities.</b> Jev does not say "HOLD". It says how likely each call is, given the evidence it was shown. The five numbers add up to 100%. The call with the most probability is the verdict.</p>
<p><b>Confidence (0 to 1).</b> How concentrated that probability is. All of it on one call gives 1.0. Spread evenly across the five gives about 0. We label 0.70 and above <b>high</b>, 0.40 to 0.70 <b>medium</b>, below 0.40 <b>low</b>.</p>
<p><b>80% interval.</b> Put the five calls in order from SELL to BUY. The interval is the narrowest range of calls that holds 80% of Jev's probability. A narrow interval (for example "ACCUMULATE alone") means Jev is sure. A wide one (for example "SELL to ACCUMULATE") means the evidence genuinely cuts both ways, and the verdict should be treated as a weak lean, not a conviction.</p>
<div class="note">This interval comes from Jev's own probability spread for one reading of the evidence. It is not a statistical interval from repeated runs, and it is not a probability that the stock goes up. It measures how divided the evidence is.</div>
<p><b>Valuation score (0 to 3).</b> 0 = expensive, 1 = fully valued, 2 = modestly cheap, 3 = undervalued. <b>Downside risk (0 to 3).</b> 0 = low, 1 = moderate, 2 = elevated, 3 = severe. Each comes with its own probability spread and interval.</p>
<p><b>Two yes/no checks on Claude.</b> "Do the figures justify Claude's call?" and "Is every claim in Claude's thesis consistent with the figures?" Each is a probability of yes. These are the feedback Claude receives before it revises.</p>
</div>

<div class="page">
<h2>What is sent at each step, in plain English</h2>
<table>
<tr><th style="width:24%">Step</th><th>What goes out</th><th style="width:30%">What comes back</th></tr>
<tr><td>2. JARVIS to the market-data feed</td><td>The ticker.</td><td>Price and about 40 financial fields, analyst targets, broker actions, moving averages.</td></tr>
<tr><td>4. JARVIS to Claude</td><td>Every number from step 2, the rule scorecard, the street consensus, and a brief: write the note as an institutional analyst, propose DCF assumptions, give a verdict and a target.</td><td>The written note, the assumptions, a verdict, a one-line reason, a price target, scenarios, peer comps.</td></tr>
<tr><td>6. JARVIS to Jev (round 1)</td><td>The company and horizon. All the numbers and the company's business description. The scorecard with each factor's value and signal. The valuation triangulation: all six methods with each one's gap to the price. The DCF detail: assumptions, WACC, the 5-year schedule, the EV-to-equity bridge. The technicals. The street consensus with the rating spread and recent broker moves. The data-quality check. Claude's whole note. Then five questions: the call (a choice of five), valuation weighing every method (0 to 3), downside risk (0 to 3), and the two yes/no checks on Claude.</td><td>A probability for each of the five calls, a confidence, the two scores with their own spreads, and the two yes/no probabilities.</td></tr>
<tr><td>7. JARVIS to Claude (round 2)</td><td>The original brief and numbers again, Claude's own round-1 answer, and Jev's feedback in words: the verdict and spread, the valuation and risk scores, the two yes/no probabilities, and one instruction: reconcile your call with the numbers or defend it with specific figures; return the same structure, revised.</td><td>The revised note, assumptions, verdict and target.</td></tr>
<tr><td>8. JARVIS to Jev (round 2)</td><td>Exactly what was sent in round 1, with Claude's revised note and the DCF recomputed from the revised assumptions.</td><td>The final probabilities, confidence, interval and scores.</td></tr>
<tr><td>9. JARVIS, in code</td><td colspan="2">Checks Jev's call against the six methods and warns if it contradicts most of them. Compares round 2 with round 1: if Jev's confidence rose while its checks on Claude fell, the trail says the revision may be written to please the judge. Turns the spread into sizing: the stance (expected position from −2 SELL to +2 BUY) picks the action, and the width of the 80% interval scales it down when the evidence is divided.</td></tr>
<tr><td>10. JARVIS to you</td><td colspan="2">The spoken line leads with the call, Jev's confidence and the interval, then the DCF value against the price. The chat, Excel cover and PDF carry the full spread, both scores, the two checks, the method check, the sizing, what Claude and the rules said, and this step-by-step trail. The decision is appended to a log; the calibration tool later compares each call with what the price did.</td></tr>
</table>
<p>Cost and time: each Jev round reads about 3,500 to 6,000 words of evidence and costs well under one US cent. The second Claude round is what adds time, roughly one to two minutes.</p>
</div>

<div class="page">
<h2>Worked example: {E(r.get("name", "?"))} ({E(r.get("symbol", "?"))})</h2>
<div class="sub">A real run on {date.today().strftime("%d %B %Y")}, at a market price of Rs {price:,.0f}.</div>
<div class="kpi">
 <div>Final call<b>{E(r.get("verdict", "?"))}</b></div>
 <div>Jev confidence<b>{j.get("confidence", 0):.2f} ({E(j.get("conviction", "?"))})</b></div>
 <div>80% interval<b>{E(interval_txt)}</b></div>
 <div>DCF fair value<b>{"Rs " + format(fv, ",.0f") if fv else "n/a"}</b></div>
 <div>Claude's target<b>{"Rs " + format(tgt, ",.0f") if tgt else "n/a"}</b></div>
</div>
<p><b>Jev's final probability spread</b></p>
{bars}
<p style="margin-top:8px"><b>Valuation</b> {j.get("valuation", {}).get("score", 0):.1f}/3 ({E(j.get("valuation", {}).get("label", "?"))}) ·
<b>Downside risk</b> {j.get("downside_risk", {}).get("score", 0):.1f}/3 ({E(j.get("downside_risk", {}).get("label", "?"))})
{("· <b>Figures justify Claude's call</b> " + format(j["numbers_back_verdict"]*100, ".0f") + "%") if j.get("numbers_back_verdict") is not None else ""}
{("· <b>Thesis consistent with figures</b> " + format(j["thesis_consistent"]*100, ".0f") + "%") if j.get("thesis_consistent") is not None else ""}</p>
<p><b>Inputs to that call:</b> Claude said {E(str((j.get("agreement") or {}).get("claude")))}; the rule scorecard said {E(str((j.get("agreement") or {}).get("quant")))}.</p>
{tri_table}
<p>{E(j.get("method_check") or "")}</p>
<p><b>{E(j.get("sizing") or "")}</b></p>
</div>

<div>
<h2>The same example, step by step</h2>
{steps_html}
</div>
</body></html>'''

html_path = out.with_suffix(".html")
html_path.write_text(doc)
subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                f"--print-to-pdf={out}", str(html_path)], check=True,
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
html_path.unlink()
print(f"wrote {out} ({out.stat().st_size:,} bytes)")
