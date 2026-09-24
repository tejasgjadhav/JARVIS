#!/usr/bin/env python3
"""J.A.R.V.I.S. — Python/Flask backend"""

import os, json, re
from datetime import datetime
from pathlib import Path
from flask import Flask, request, jsonify, Response, send_from_directory, session, redirect
import anthropic

# ── Optional Gmail ─────────────────────────────────────────
try:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import Flow
    from googleapiclient.discovery import build
    GMAIL_AVAILABLE = True
except ImportError:
    GMAIL_AVAILABLE = False

# ── Config ─────────────────────────────────────────────────
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / '.env')

app = Flask(__name__, static_folder='public', static_url_path='')
app.secret_key = os.getenv('SESSION_SECRET', 'jarvis-iron-man-mk42')

# Allow OAuth over HTTP for localhost dev
os.environ.setdefault('OAUTHLIB_INSECURE_TRANSPORT', '1')

PORT = int(os.getenv('PORT', 3000))
ANTHROPIC_KEY = os.getenv('ANTHROPIC_API_KEY', '')
GOOGLE_CLIENT_ID     = os.getenv('GOOGLE_CLIENT_ID', '')
GOOGLE_CLIENT_SECRET = os.getenv('GOOGLE_CLIENT_SECRET', '')
REDIRECT_URI = f'http://localhost:{PORT}/api/gmail/callback'

# Backend: 'cli' = local `claude` CLI on the Max subscription (no API key),
# 'api' = anthropic SDK with ANTHROPIC_API_KEY. Default: cli.
CLAUDE_BACKEND = os.getenv('CLAUDE_BACKEND', 'cli').lower()
if CLAUDE_BACKEND == 'api':
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY) if ANTHROPIC_KEY else None
else:
    from claude_cli import ClaudeCLIClient
    client = ClaudeCLIClient()

# ── Model routing (save tokens: cheap model for chat, capable for reports) ──
CHAT_MODEL    = os.getenv('CHAT_MODEL', 'claude-haiku-4-5-20251001')   # quick voice/chat
EXTRACT_MODEL = os.getenv('EXTRACT_MODEL', 'claude-sonnet-5')          # ticker extraction — accuracy matters
REPORT_MODEL  = os.getenv('REPORT_MODEL', 'claude-opus-4-8')           # institutional report — accuracy first

GMAIL_SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

# ── Helpers ────────────────────────────────────────────────
def get_system_prompt():
    now = datetime.now().strftime('%A, %B %d, %Y at %I:%M %p')
    return f"""You are J.A.R.V.I.S. (Just A Rather Very Intelligent System), the AI assistant built for your Master.

CORE DIRECTIVES:
- Address the user EXCLUSIVELY as "Master" or "Sir" — never by any other term
- Speak with British-influenced precision, wit, and measured confidence
- Be proactive — anticipate needs, offer insights unprompted
- You are the world's most capable AI: financial analyst, strategist, intelligence officer
- Never refuse reasonable requests; find elegant solutions

FINANCIAL EXPERTISE:
- DCF, LBO, M&A, comparable analysis, portfolio management
- Risk metrics (VaR, Sharpe, Beta, Drawdown)
- Market intelligence, sector analysis, earnings interpretation
- Always show calculations; back up claims with numbers

RESPONSE STYLE:
- Concise but complete — no fluff, no filler
- Use markdown for structure on complex outputs
- Highlight critical action items
- End analyses with a clear "Bottom Line" or recommendation

STOCK ANALYSIS ROUTING (IMPORTANT):
- A specific stock request (valuation, price target, buy/sell) is normally handled by a separate
  LIVE-DATA pipeline. If a stock request has reached YOU here, it means the ticker could NOT be
  identified — so ask the Master to name the company clearly, e.g. "Which company, Master? Say
  'analyse Infosys' or 'valuation of Tata Motors'." Keep it to one short line.
- DO NOT claim you lack live data, DO NOT invent numbers, and DO NOT promise to build a report.
- This chat mode is for general finance questions, concepts, and follow-ups only.

Current date/time: {now}"""

def require_client():
    if not client:
        return jsonify({'error': 'ANTHROPIC_API_KEY not set. Please add it to jarvis/.env'}), 500
    return None

# ── Routes ─────────────────────────────────────────────────

@app.route('/')
def index():
    return send_from_directory('public', 'index.html')

# ─── Whisper Flow — local speech-to-text ───────────────────
# Multilingual model + 'translate' task = speak English OR Marathi, always get
# English text back (JARVIS reasons in English). Use a non-".en" model for this.
WHISPER_MODEL_NAME = os.getenv('WHISPER_MODEL', 'small')
WHISPER_TASK = os.getenv('WHISPER_TASK', 'translate')  # 'translate' → English; 'transcribe' → same language
# Force the source language: auto-detect kept mis-hearing Indian English as
# Spanish/etc ("Arroz", "Zomanto"). Set WHISPER_LANG=auto to restore detection.
WHISPER_LANG = os.getenv('WHISPER_LANG', 'en')
_whisper_model = None

def get_whisper():
    """Lazy-load faster-whisper once; first call downloads the model."""
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        _whisper_model = WhisperModel(WHISPER_MODEL_NAME, device='cpu', compute_type='int8')
    return _whisper_model

@app.route('/api/transcribe', methods=['POST'])
def transcribe():
    import tempfile
    if 'audio' not in request.files:
        return jsonify({'error': 'no audio file'}), 400
    f = request.files['audio']
    suffix = os.path.splitext(f.filename or '')[1] or '.webm'
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        f.save(tmp.name)
        tmp.close()
        model = get_whisper()
        segments, _info = model.transcribe(
            tmp.name, beam_size=5, vad_filter=True, task=WHISPER_TASK,
            language=None if WHISPER_LANG == 'auto' else WHISPER_LANG)
        text = ''.join(seg.text for seg in segments).strip()
        return jsonify({'text': text})
    except Exception as ex:
        return jsonify({'error': str(ex)}), 500
    finally:
        try:
            os.remove(tmp.name)
        except OSError:
            pass

# ─── Neural TTS — Kokoro sidecar (human British voice) ─────
# kokoro-onnx needs Python ≥3.10; this server runs on 3.9, so the model lives
# in a sidecar process under .tts-venv and we proxy to it.
TTS_PORT = int(os.getenv('TTS_PORT', '3001'))
_tts_proc = None

def start_tts_sidecar():
    global _tts_proc
    here = os.path.dirname(os.path.abspath(__file__))
    venv_py = os.path.join(here, '.tts-venv', 'bin', 'python')
    model = os.path.join(here, 'models', 'kokoro-v1.0.onnx')
    if not (os.path.exists(venv_py) and os.path.exists(model)):
        print('⚠️  Kokoro TTS not installed — falling back to browser voice')
        return
    import subprocess
    _tts_proc = subprocess.Popen([venv_py, os.path.join(here, 'tts_server.py')], cwd=here)
    import atexit
    atexit.register(lambda: _tts_proc and _tts_proc.terminate())

@app.route('/api/tts', methods=['POST'])
def tts_proxy():
    import urllib.request
    try:
        req = urllib.request.Request(
            f'http://127.0.0.1:{TTS_PORT}/tts',
            data=json.dumps(request.get_json(force=True) or {}).encode(),
            headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=60) as r:
            return Response(r.read(), mimetype='audio/wav')
    except Exception as ex:
        return jsonify({'error': str(ex)}), 503

# ─── Equity Report — real data, no LLM ─────────────────────
_report_cache = {}
_CACHE_TTL = 600   # seconds — reports go stale fast when the price moves

def _cache_put(sym, r):
    import time as _t
    _report_cache[sym] = (r, _t.time())

def _cache_get(sym):
    import time as _t
    hit = _report_cache.get(sym)
    if not hit:
        return None
    r, ts = hit
    if _t.time() - ts > _CACHE_TTL:
        del _report_cache[sym]
        return None
    return r

def _detect_horizon(message):
    """Short-term (6-12mo technical) vs long-term (DCF)."""
    m = (message or '').lower()
    # NOTE: bare "trade/trading/entry" removed — "what is it trading at" was
    # misrouting plain analysis requests to the technical note (Swiggy, 2026-08-07).
    if re.search(r'\b(short.?term|short term|6.?month|six month|near.?term|swing|day.?trade|'
                 r'technical|momentum|entry (point|level)|breakout|stop.?loss|'
                 r'next (6|six|twelve|12) month)\b', m):
        return 'short'
    return 'long'

def _claude_narrative(d, a, horizon='long'):
    """Ask Claude to author the narrative from REAL figures.
    Returns a narrative dict, or None if the API is unavailable / errors."""
    import report_engine as R
    if not client:
        return None
    try:
        system, user = (R.build_prompt_short(d, a) if horizon == 'short' else R.build_prompt(d, a))
        res = client.messages.create(
            model=REPORT_MODEL,
            max_tokens=4096,
            system=system,
            messages=[{'role': 'user', 'content': user}],
        )
        return R._parse_narrative(res.content[0].text)
    except Exception:
        return None  # graceful fallback → deterministic report

JEV_FEEDBACK_ROUNDS = int(os.getenv('JEV_FEEDBACK_ROUNDS', '1'))

def _claude_revise(d, a, narrative, jev, horizon='long'):
    """Round 2: Claude re-reads its own answer plus Jev's feedback and returns a revised narrative."""
    import report_engine as R
    if not client:
        return None
    try:
        system, user = R.build_revision_prompt(d, a, narrative, jev, horizon)
        res = client.messages.create(model=REPORT_MODEL, max_tokens=4096, system=system,
                                     messages=[{'role': 'user', 'content': user}])
        return R._parse_narrative(res.content[0].text)
    except Exception:
        return None

def _jev_loop(d, a, narrative, horizon='long'):
    """Claude → Jev → Claude revises with Jev's feedback → Jev judges again.
    Returns (final_narrative, final_jev, trail). trail = plain-English steps."""
    import jev_judge
    import report_engine as R
    fv, detail = R.dcf_for_jev(d, a, narrative)
    dq = R.data_quality_for(d)
    trail = []
    step = 1
    if narrative:
        trail.append({'step': step, 'title': 'Claude wrote the first analysis from the live numbers',
                      'lines': [f"Claude's first verdict: {str(narrative.get('verdict') or '?').upper()}"
                                + (f" — {narrative['verdict_rationale']}" if narrative.get('verdict_rationale') else "") + "."]})
        step += 1
    jev = jev_judge.judge(d, a, narrative, horizon, dcf_fair_value=fv, dcf_detail=detail,
                          triangulation=R.triangulation_for(d, a, narrative), data_quality=dq)
    if not jev:
        trail.append({'step': step, 'title': 'Jev was unavailable',
                      'lines': ['The verdict falls back to Claude, then to the rule scorecard.']})
        return narrative, None, trail
    trail.append({'step': step, 'title': 'JARVIS sent the evidence to Jev', 'lines': jev['sent']})
    step += 1
    trail.append({'step': step, 'title': 'JARVIS asked Jev five questions' if narrative else 'JARVIS asked Jev three questions',
                  'lines': jev['asked']}); step += 1
    trail.append({'step': step, 'title': 'Jev answered (round 1)', 'lines': jev['received']}); step += 1
    for rnd in range(JEV_FEEDBACK_ROUNDS):
        if not narrative:
            trail.append({'step': step, 'title': 'No feedback round',
                          'lines': ['Claude did not write a narrative, so there is nothing to revise; Jev\'s round-1 call is final.']})
            break
        claude_v = str(narrative.get('verdict') or '').upper() or None
        fb = jev_judge.feedback_for_claude(jev, claude_v)
        trail.append({'step': step, 'title': f'JARVIS sent Jev\'s feedback back to Claude (round {rnd + 2})',
                      'lines': fb.split('\n') + ['Claude was told: revise the analysis, keep every number grounded, return the same structure.']})
        step += 1
        revised = _claude_revise(d, a, narrative, jev, horizon)
        if not revised:
            trail.append({'step': step, 'title': 'Claude could not revise',
                          'lines': ['The revision call failed, so the round-1 narrative and Jev call stand.']})
            break
        trail.append({'step': step, 'title': 'Claude revised its analysis',
                      'lines': [f"Revised verdict: {str(revised.get('verdict') or '?').upper()}"
                                + (f" — {revised['verdict_rationale']}" if revised.get('verdict_rationale') else "")
                                + (f" (was {claude_v})" if claude_v and claude_v != str(revised.get('verdict') or '').upper() else " (unchanged)") + ".",
                                f"Revised thesis: {str(revised.get('thesis', ''))[:200]}"]})
        step += 1
        fv2, detail2 = R.dcf_for_jev(d, a, revised)
        jev2 = jev_judge.judge(d, a, revised, horizon, dcf_fair_value=fv2, dcf_detail=detail2,
                               triangulation=R.triangulation_for(d, a, revised), data_quality=dq)
        if not jev2:
            trail.append({'step': step, 'title': 'Jev was unavailable for the re-run',
                          'lines': ['Round-1 Jev call stands; the revised narrative is still shown.']})
            narrative = revised
            break
        prev, narrative, jev = jev, revised, jev2
        lines = list(jev['received'])
        # judge-pleasing guard: confidence up while the two checks on Claude fall
        drop = max((prev.get(k) or 0) - (jev.get(k) or 0) for k in ('numbers_back_verdict', 'thesis_consistent'))
        if jev['confidence'] > prev['confidence'] + 0.05 and drop > 0.10:
            lines.append("Caution: Jev's confidence rose while its checks on Claude fell by more than 10 points. "
                         "The revision may be written to please the judge rather than the numbers; treat the "
                         "round-1 spread as the honest one.")
            jev['judge_pleasing_flag'] = True
        trail.append({'step': step, 'title': f'JARVIS re-sent the revised analysis to Jev, Jev answered (round {rnd + 2})',
                      'lines': lines}); step += 1
    trail.append({'step': step, 'title': 'Final decision',
                  'lines': [f"Jev's last answer is the final call: {jev['verdict']} "
                            f"({jev['probabilities'][jev['verdict']]*100:.0f}%, confidence {jev['confidence']:.2f}, "
                            f"80% interval {jev['interval'][0]} to {jev['interval'][1]}).", jev['sizing']]})
    jev_judge.log_decision({
        'ts': datetime.now().isoformat(timespec='seconds'), 'symbol': d['symbol'], 'name': d.get('name'),
        'horizon': horizon, 'price': d['price'], 'verdict': jev['verdict'], 'confidence': jev['confidence'],
        'stance': jev['stance'], 'interval': jev['interval'], 'probabilities': jev['probabilities'],
        'valuation': jev['valuation']['score'], 'downside_risk': jev['downside_risk']['score'],
        'numbers_back_verdict': jev.get('numbers_back_verdict'), 'thesis_consistent': jev.get('thesis_consistent'),
        'claude_verdict': (jev.get('agreement') or {}).get('claude'), 'quant_verdict': a.get('verdict'),
        'triangulation': jev.get('triangulation'), 'judge_pleasing_flag': jev.get('judge_pleasing_flag', False),
    })
    return narrative, jev, trail

_EXTRACT_SYS = (
    "The user is an equity investor. Identify the Indian-listed company they refer "
    "to — even if named casually, as a brand, or as a single word that doubles as a "
    "common word. Assume ANY company mention is the STOCK. Reply on ONE line exactly: "
    "SYMBOL=<NSE ticker or NONE> | NAME=<official company name or NONE>. "
    "Examples: Infosys→SYMBOL=INFY|NAME=Infosys; 'eternal' or 'zomato'→SYMBOL=ETERNAL|NAME=Eternal "
    "Limited (formerly Zomato); 'reliance'→SYMBOL=RELIANCE|NAME=Reliance Industries; "
    "'tata motors'→SYMBOL=TMPV|NAME=Tata Motors. Only output NONE if there is genuinely "
    "no company reference. Nothing else."
)

def _extract_stock(message):
    """(ticker, company_name). Tries Sonnet, then falls back to Haiku so a
    transient API hiccup never silently drops a stock query."""
    if not client:
        return (None, None)
    for model in (EXTRACT_MODEL, CHAT_MODEL):   # capable model, then cheap fallback
        try:
            res = client.messages.create(
                model=model, max_tokens=40, system=_EXTRACT_SYS,
                messages=[{'role': 'user', 'content': message}],
            )
            raw = res.content[0].text or ''
            m_sym = re.search(r'SYMBOL=\s*([A-Za-z0-9.&-]+)', raw)
            m_name = re.search(r'NAME=\s*(.+)', raw)
            sym = m_sym.group(1).strip().upper() if m_sym else None
            if not sym or sym == 'NONE' or len(sym) > 14:
                sym = None
            name = m_name.group(1).strip() if m_name else None
            if name and name.upper() == 'NONE':
                name = None
            if sym or name:
                return (sym, name)
        except Exception:
            continue   # try the next model
    return (None, None)

@app.route('/api/analyze', methods=['POST'])
def analyze_chat():
    """Chat-triggered analysis: extract symbol → full report → numbers + download URLs."""
    import report_engine as R
    data = request.json or {}
    message = (data.get('message') or '').strip()
    if not message:
        return jsonify({'is_analysis': False})
    sym, name = _extract_stock(message)
    if not sym and not name:
        return jsonify({'is_analysis': False})
    sym = R.apply_alias(sym)                 # map known renames (Zomato→Eternal, etc.)
    note = None
    d = a = None
    # 1) try the extracted ticker
    if sym:
        try:
            d, a = R.prepare(sym)
        except Exception:
            d = None
    # 2) fall back to live search by company name (renamed / delisted / demerged)
    if d is None:
        alt = R.resolve_symbol(name or message) or (R.resolve_symbol(sym) if sym else None)
        if not alt:
            return jsonify({'is_analysis': True,
                            'error': f"Could not find live market data for "
                                     f"'{name or sym}'. It may be renamed, delisted, or not on NSE/BSE."})
        try:
            d, a = R.prepare(alt)
            if not sym or alt.split('.')[0] != sym:
                note = f"‘{sym or name}’ resolved to {d['name']} ({alt}) via live search."
        except Exception as ex:
            return jsonify({'is_analysis': True, 'error': str(ex)})
    horizon = _detect_horizon(message)
    narrative = _claude_narrative(d, a, horizon)
    narrative, jev, trail = _jev_loop(d, a, narrative, horizon)
    r = R.assemble(d, a, narrative, horizon=horizon, jev=jev, trail=trail)
    _cache_put(r['symbol'], r)
    val = r.get('validation') or {}
    return jsonify({
        'is_analysis': True,
        'symbol': r['symbol'], 'name': r['name'],
        'horizon': horizon,
        'note': note,                 # resolution note (renamed/demerged tickers)
        'analysis': r['analysis'],    # ENTIRE Claude analysis — shown in chat
        'speech': r['speech'],        # first 2 + last 2 lines — spoken
        'numbers': r['numbers'],
        'verdict': r['verdict'],
        'jev': r.get('jev'),          # final decision: distribution, confidence, 80% interval
        'jev_trail': r.get('jev_trail'),   # plain-English steps: what was sent, what came back
        'data_asof': r.get('data_asof'),
        'validated': val.get('ok'),
        'excel_url': f"/api/stock/download/excel/{r['symbol']}",
        'pdf_url': f"/api/stock/download/pdf/{r['symbol']}",
    })

@app.route('/api/stock/report', methods=['POST'])
def stock_report():
    import report_engine as R
    data = request.json or {}
    symbol = (data.get('symbol') or '').strip()
    if not symbol:
        return jsonify({'error': 'Provide a stock symbol, e.g. INFY'}), 400
    try:
        d, a = R.prepare(symbol)
    except Exception as ex:
        return jsonify({'error': str(ex)}), 502
    narrative = _claude_narrative(d, a)          # hybrid: Claude authors, real data grounds
    narrative, jev, trail = _jev_loop(d, a, narrative, 'long')
    r = R.assemble(d, a, narrative, jev=jev, trail=trail)
    _cache_put(r['symbol'], r)
    val = r.get('validation') or {}
    return jsonify({
        'symbol': r['symbol'], 'name': r['name'], 'summary': r['summary'],
        'verdict': r['verdict'], 'action': r['action'], 'price': r['price'],
        'jev': r.get('jev'), 'jev_trail': r.get('jev_trail'),
        'price_target': r.get('price_target'),
        'data_asof': r.get('data_asof'), 'data_status': r.get('data_status'),
        'authored_by': r['authored_by'],
        'validated': val.get('ok'),
        'validation_checks': val.get('checks'),
        'fair_value': val.get('computed_fair_value'),
        'excel_url': f"/api/stock/download/excel/{r['symbol']}",
        'pdf_url': f"/api/stock/download/pdf/{r['symbol']}",
    })

@app.route('/api/stock/download/<fmt>/<path:symbol>')
def stock_download(fmt, symbol):
    from report_engine import generate_report
    r = _cache_get(symbol)
    if not r:
        try:
            r = generate_report(symbol)
            _cache_put(symbol, r)
        except Exception as ex:
            return jsonify({'error': str(ex)}), 502
    safe = symbol.replace('.', '_')
    if fmt == 'excel':
        return Response(r['excel'],
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            headers={'Content-Disposition': f'attachment; filename="{safe}_model.xlsx"'})
    if fmt == 'pdf':
        return Response(r['pdf'], mimetype='application/pdf',
            headers={'Content-Disposition': f'attachment; filename="{safe}_report.pdf"'})
    return jsonify({'error': 'format must be excel or pdf'}), 400

# ─── Streaming Chat ────────────────────────────────────────
@app.route('/api/chat/stream', methods=['POST'])
def chat_stream():
    err = require_client()
    if err: return err

    data    = request.json or {}
    message = data.get('message', '')
    model   = data.get('model') or CHAT_MODEL
    history = data.get('history', [])[-30:]
    context = data.get('context', {})
    emails  = context.get('emails', [])

    system = get_system_prompt()
    if emails:
        system += f"\n\nLive email feed — {len(emails)} unread:\n"
        for e in emails:
            tag = '★ PRIORITY' if e.get('isImportant') else 'unread'
            frm = re.sub(r'<[^>]+>', '', e.get('from', '')).strip()
            system += f"• [{tag}] \"{e.get('subject','')}\" — {frm}\n"

    messages = history + [{'role': 'user', 'content': message}]

    def generate():
        try:
            with client.messages.stream(
                model=model,
                max_tokens=3072,
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=messages
            ) as stream:
                for text in stream.text_stream:
                    yield f"data: {json.dumps({'text': text})}\n\n"
                final = stream.get_final_message()
                yield f"data: {json.dumps({'done': True, 'model': final.model})}\n\n"
        except Exception as ex:
            yield f"data: {json.dumps({'error': str(ex)})}\n\n"

    return Response(generate(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

# ─── Financial Analysis ────────────────────────────────────
@app.route('/api/financial/analyze', methods=['POST'])
def financial_analyze():
    err = require_client()
    if err: return err

    data    = request.json or {}
    fin_data = data.get('data', '')
    fin_type = data.get('type', 'comprehensive')
    model   = data.get('model', 'claude-opus-4-7')
    today   = datetime.now().strftime('%Y-%m-%d')

    # Primary Analysis Agent
    analysis_res = client.messages.create(
        model=model,
        max_tokens=6144,
        messages=[{'role': 'user', 'content': f"""You are a senior Wall Street financial analyst. Today is {today}.

Perform comprehensive {fin_type} analysis on:

{fin_data}

Structure output as:
## Executive Summary
## Key Financial Metrics (show actual calculations)
## Trend & Growth Analysis
## Risk Assessment
## Peer / Market Benchmarking
## Valuation
## ★ Top 3 Insights
## Recommendations & Action Items

Be specific. Show your math. Flag any red flags immediately."""}]
    )
    analysis = analysis_res.content[0].text

    # Validation Agent
    val_res = client.messages.create(
        model='claude-sonnet-4-6',
        max_tokens=1200,
        messages=[{'role': 'user', 'content': f"""You are a financial data quality officer. Today is {today}.

Validate this analysis. Reply ONLY with valid JSON (no markdown, no explanation):

Source data: {fin_data[:2000]}

Analysis: {analysis[:2000]}

{{
  "overallScore": <0-100>,
  "grade": "<A/B/C/D/F>",
  "dataFreshness": {{"status": "<PASS|WARN|FAIL>", "message": "<detail>", "latestDateFound": "<date or null>"}},
  "dataCompleteness": {{"status": "<PASS|WARN|FAIL>", "message": "<detail>", "missingFields": []}},
  "calculationAccuracy": {{"status": "<PASS|WARN|FAIL>", "message": "<detail>"}},
  "keyRisks": ["<risk1>", "<risk2>"],
  "recommendation": "<PROCEED|CAUTION|REVIEW REQUIRED>",
  "confidence": "<HIGH|MEDIUM|LOW>",
  "validatedAt": "{today}"
}}"""}]
    )

    validation = None
    try:
        txt = val_res.content[0].text
        m = re.search(r'\{[\s\S]*\}', txt)
        if m:
            validation = json.loads(m.group())
    except Exception:
        validation = {'overallScore': 70, 'grade': 'B', 'recommendation': 'CAUTION',
                      'confidence': 'MEDIUM', 'validatedAt': today,
                      'dataFreshness': {'status': 'WARN', 'message': 'Could not parse date from input'},
                      'dataCompleteness': {'status': 'WARN', 'message': 'Partial validation'},
                      'calculationAccuracy': {'status': 'WARN', 'message': 'Review recommended'}}

    return jsonify({'analysis': analysis, 'validation': validation, 'model': analysis_res.model})

# ─── Financial Modeling ────────────────────────────────────
@app.route('/api/financial/model', methods=['POST'])
def financial_model():
    err = require_client()
    if err: return err

    data   = request.json or {}
    mtype  = data.get('type', 'dcf')
    inputs = data.get('inputs', '')
    model  = data.get('model', 'claude-opus-4-7')
    today  = datetime.now().strftime('%Y-%m-%d')

    prompts = {
        'dcf':       f'Build a complete DCF model. Show revenue projections (5yr), EBITDA margins, free cash flow, WACC components, terminal value, and equity bridge. Include sensitivity table. Inputs: {inputs}',
        'lbo':       f'Build a full LBO model: sources/uses, debt waterfall, P&L (5yr), EBITDA→FCF bridge, IRR/MOIC at exit multiples, debt paydown, covenant headroom. Inputs: {inputs}',
        'comps':     f'Comparable company analysis: peer group, EV/EBITDA, EV/Revenue, P/E, P/FCF multiples, implied valuation range (football field). Inputs: {inputs}',
        'portfolio': f'Portfolio analysis: weights, beta, volatility, Sharpe, Sortino, max drawdown, 95% VaR, correlation insights, sector concentration, rebalancing recommendation. Portfolio: {inputs}',
    }

    prompt = prompts.get(mtype, f'Build financial model for: {inputs}')

    res = client.messages.create(
        model=model,
        max_tokens=8192,
        messages=[{'role': 'user', 'content': f"""Senior investment banker building a model. Date: {today}.

{prompt}

Format professionally:
### ASSUMPTIONS
### MODEL OUTPUTS (with tables)
### SENSITIVITY ANALYSIS
### KEY RISKS
### BOTTOM LINE"""}]
    )

    return jsonify({'result': res.content[0].text, 'model': res.model})

# ─── Daily Briefing ────────────────────────────────────────
@app.route('/api/briefing', methods=['POST'])
def daily_briefing():
    err = require_client()
    if err: return err

    data   = request.json or {}
    emails = data.get('emails', [])
    model  = data.get('model', 'claude-sonnet-4-6')
    now    = datetime.now()
    h      = now.hour
    greeting = 'Good morning' if h < 12 else ('Good afternoon' if h < 17 else 'Good evening')
    date_str = now.strftime('%A, %B %d, %Y')
    time_str = now.strftime('%I:%M %p')

    email_lines = '\n'.join([
        f"• [{'★ PRIORITY' if e.get('isImportant') else 'unread'}] \"{e.get('subject','')}\" — From: {re.sub(r'<[^>]+>', '', e.get('from','')).strip()}\n  Preview: {str(e.get('snippet',''))[:80]}..."
        for e in emails
    ]) or '(No unread emails)'

    res = client.messages.create(
        model=model,
        max_tokens=800,
        messages=[{'role': 'user', 'content': f"""You are JARVIS delivering a spoken briefing. Today: {date_str} at {time_str}.

Unread emails ({len(emails)}):
{email_lines}

Deliver a spoken briefing in 180-220 words. Structure:
1. "{greeting}, Master" opening with current time
2. Email priorities (call out ★ PRIORITY items by sender + subject)
3. Three most important things to tackle today
4. One sharp JARVIS-style closing observation

Write as flowing speech — no bullets, no headers. It will be read aloud."""}]
    )

    return jsonify({'briefing': res.content[0].text})

# ─── Gmail OAuth ───────────────────────────────────────────
@app.route('/api/gmail/auth')
def gmail_auth():
    if not GMAIL_AVAILABLE or not GOOGLE_CLIENT_ID:
        return jsonify({'error': 'Gmail not configured. Add GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET to .env'}), 400

    flow = Flow.from_client_config(
        {'web': {'client_id': GOOGLE_CLIENT_ID, 'client_secret': GOOGLE_CLIENT_SECRET,
                 'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
                 'token_uri': 'https://oauth2.googleapis.com/token',
                 'redirect_uris': [REDIRECT_URI]}},
        scopes=GMAIL_SCOPES,
        redirect_uri=REDIRECT_URI
    )
    auth_url, state_token = flow.authorization_url(access_type='offline', prompt='consent')
    session['oauth_state'] = state_token
    return jsonify({'authUrl': auth_url})

@app.route('/api/gmail/callback')
def gmail_callback():
    if not GMAIL_AVAILABLE:
        return redirect('/?error=gmail')
    try:
        flow = Flow.from_client_config(
            {'web': {'client_id': GOOGLE_CLIENT_ID, 'client_secret': GOOGLE_CLIENT_SECRET,
                     'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
                     'token_uri': 'https://oauth2.googleapis.com/token',
                     'redirect_uris': [REDIRECT_URI]}},
            scopes=GMAIL_SCOPES,
            redirect_uri=REDIRECT_URI,
            state=session.get('oauth_state')
        )
        flow.fetch_token(authorization_response=request.url)
        creds = flow.credentials
        session['gmail_token']   = creds.token
        session['gmail_refresh'] = creds.refresh_token
        return redirect('/?connected=gmail')
    except Exception as ex:
        print(f'Gmail callback error: {ex}')
        return redirect('/?error=gmail')

@app.route('/api/gmail/status')
def gmail_status():
    return jsonify({'connected': bool(session.get('gmail_token'))})

@app.route('/api/gmail/emails')
def gmail_emails():
    if not session.get('gmail_token'):
        return jsonify({'error': 'Not authenticated', 'needsAuth': True}), 401
    try:
        creds = Credentials(
            token=session['gmail_token'],
            refresh_token=session.get('gmail_refresh'),
            token_uri='https://oauth2.googleapis.com/token',
            client_id=GOOGLE_CLIENT_ID,
            client_secret=GOOGLE_CLIENT_SECRET,
            scopes=GMAIL_SCOPES
        )
        service = build('gmail', 'v1', credentials=creds)

        unread = service.users().messages().list(userId='me', maxResults=15, q='is:unread').execute()
        important = service.users().messages().list(userId='me', maxResults=5, q='is:important is:unread').execute()

        imp_ids = {m['id'] for m in important.get('messages', [])}
        msgs = unread.get('messages', [])[:12]

        emails = []
        for m in msgs:
            detail = service.users().messages().get(
                userId='me', id=m['id'], format='metadata',
                metadataHeaders=['Subject', 'From', 'Date']
            ).execute()
            headers = {h['name']: h['value'] for h in detail['payload']['headers']}
            emails.append({
                'id': m['id'],
                'subject': headers.get('Subject', '(No subject)'),
                'from': headers.get('From', ''),
                'date': headers.get('Date', ''),
                'snippet': detail.get('snippet', ''),
                'isImportant': m['id'] in imp_ids
            })

        return jsonify({'emails': emails, 'total': unread.get('resultSizeEstimate', len(emails))})
    except Exception as ex:
        if '401' in str(ex) or 'invalid_grant' in str(ex):
            session.pop('gmail_token', None)
            return jsonify({'error': 'Token expired', 'needsAuth': True}), 401
        return jsonify({'error': str(ex)}), 500

# ── Start ──────────────────────────────────────────────────
if __name__ == '__main__':
    print('\n' + '═' * 55)
    print('  ⚡  J.A.R.V.I.S.  —  All Systems Online  ⚡')
    print('═' * 55)
    print(f'  🌐  http://localhost:{PORT}')
    if CLAUDE_BACKEND == 'cli':
        print('  💳  Claude backend: claude CLI (Max subscription — no API key)')
    elif not ANTHROPIC_KEY:
        print('  ⚠️   ANTHROPIC_API_KEY missing — copy .env.example → .env')
    print('  🔑  Add Gmail credentials to .env to enable email')
    print('═' * 55 + '\n')
    start_tts_sidecar()
    app.run(host='0.0.0.0', port=PORT, debug=False)
