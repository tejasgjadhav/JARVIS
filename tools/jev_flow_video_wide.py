"""Landscape (16:9, 1920x1080) animated explainer for the Jev integration.

Four scenes with crossfades:
  1. Title slide: how Jev can be used in equity analysis, four uses.
  2. The pipeline as a serpentine of eight cards that enter one by one,
     a gold dot running the track between them.
  3. The verdict: Claude's HOLD struck through, the two Jev scores, the
     composed REDUCE stamping in with growing probability bars.
  4. Closing card: the takeaway, byline, disclaimer.
Prices and targets withheld (covered-person rule). Disclaimer on every scene.

Usage: python3 tools/jev_flow_video_wide.py OUT.mp4 [pace, default 1.6] [core]
  core = flow + results only, no opening or closing slide
"""
import math
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

OUT = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else Path("~/Downloads/Equity_Analyst_Agent_Jev_Flow_16x9.mp4").expanduser()
FF = "/Users/sayali/Library/Python/3.9/lib/python/site-packages/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v7.1"
W, H, FPS = 1920, 1080, 30
CREAM = (243, 238, 228); NAVY = (11, 31, 58); CLAY = (206, 100, 64); BLUE = (27, 111, 179)
GREY = (107, 122, 141); WHITE = (255, 255, 255); LIGHT = (226, 232, 240); GOLD = (222, 168, 60)
DARK = (8, 22, 42); DARK2 = (14, 38, 70)


def font(sz, bold=False):
    return ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold
                              else "/System/Library/Fonts/Supplemental/Arial.ttf", sz)


F_HOOK = font(64, True); F_HOOK2 = font(44); F_T = font(50, True); F_S = font(26)
F_CB = font(24, True); F_CD = font(20); F_BIG = font(96, True); F_M = font(34, True)
F_D = font(24); F_X = font(18); F_K = font(28, True); F_F = font(22)

STEPS = [
    ("You ask", '"Should I buy Eternal?"', CLAY),
    ("Agent pulls live numbers", "Price, P/E, growth, margins, cash flow, street targets", NAVY),
    ("Claude writes the note", "Thesis, cases, DCF assumptions, a weight per valuation method", CLAY),
    ("Agent reconciles value", "DCF, comps, SOTP, scenarios, street: one weighted fair value", NAVY),
    ("Jev scores business, price", "Two 0-3 scores, judged separately; code composes the call", BLUE),
    ("Claude revises, if needed", "Only when Jev disagrees or a check on the note fails", CLAY),
    ("Jev judges again", "The final call: verdict, confidence, 80% interval, sizing", BLUE),
    ("You get the decision", "Chat, voice, Excel, PDF, and a logged trail for calibration", CLAY),
]
PROBS = [("SELL", 0.37), ("REDUCE", 0.63), ("HOLD", 0.00), ("ACCUMULATE", 0.00), ("BUY", 0.00)]

# ── timeline ──
CORE = len(sys.argv) > 3 and sys.argv[3] == "core"   # flow + results only (no opening or closing slide)
S1 = 0.0; S1_END = 0.0 if CORE else 5.6
S2 = S1_END; STEP0 = S2 + 1.0; STEP_DT = 0.75; ENTER = 0.4; S2_END = STEP0 + 8 * STEP_DT + (1.6 if CORE else 0.6)
S3 = S2_END; S3_END = S3 + (7.5 if CORE else 6.0)
S4 = S3_END; T_END = S3_END if CORE else S4 + 4.0
XF = 0.5  # crossfade


def ease_out(x):
    x = max(0.0, min(1.0, x)); return 1 - (1 - x) ** 3


def ease_io(x):
    x = max(0.0, min(1.0, x)); return 0.5 - 0.5 * math.cos(math.pi * x)


def layer():
    return Image.new("RGBA", (W, H), (0, 0, 0, 0))


def fade(img, a):
    a = max(0.0, min(1.0, a))
    if a >= 1: return img
    img.putalpha(img.getchannel("A").point(lambda v: int(v * a))); return img


def footer(d, dark=False):
    c = (150, 165, 185) if dark else GREY
    d.text((60, H - 62), "Personal project, illustrative and educational. Not investment advice or a recommendation. Views my own, not my employer's, "
                         "who has not reviewed this. No holding or intended trade is implied. Model outputs can be wrong.", font=F_X, fill=c)
    d.text((60, H - 34), "Tejas Jadhav, CFA, FRM", font=F_K, fill=CLAY)
    d.text((W - 60 - 400, H - 30), "Jev is a TypeSafe System One model", font=F_F, fill=c)


# ── scene 1: how Jev can be used in equity analysis ──
USES = [
    ("The final gate on a call", "Reads the numbers and the note, returns a probability for each call"),
    ("A consistency check", "Does the thesis match the figures? Do the figures justify the call?"),
    ("A reranker for screening", "Score hundreds of names on the same questions, deep-dive the top few"),
    ("A calibrated score to audit", "Log every decision and check it against what prices did"),
]


def scene1(t):
    img = Image.new("RGBA", (W, H), DARK + (255,)); d = ImageDraw.Draw(img)
    g = layer(); gd = ImageDraw.Draw(g)
    for r in range(600, 0, -40):
        gd.ellipse((W // 2 - r, 540 - r, W // 2 + r, 540 + r), fill=DARK2 + (int(18 * (1 - r / 600)),))
    img.alpha_composite(g)
    title = "How Jev can be used in Equity Analysis"
    k1 = ease_out(t / 1.0)
    d.text((160, 150), title[: int(len(title) * k1)], font=F_HOOK, fill=WHITE)
    a0 = ease_out((t - 0.9) / 0.4)
    if a0 > 0:
        l = layer(); ld = ImageDraw.Draw(l)
        ld.text((160, 236), "Jev is TypeSafe's System One model. It does not write.", font=F_HOOK2, fill=GOLD + (255,))
        ld.text((160, 288), "It reads evidence and returns probabilities.", font=F_HOOK2, fill=GOLD + (255,))
        img.alpha_composite(fade(l, a0))
    for i, (head, body) in enumerate(USES):
        a = ease_out((t - 1.5 - i * 0.55) / 0.4)
        if a <= 0: continue
        y = 400 + i * 112 + int((1 - a) * 20)
        l = layer(); ld = ImageDraw.Draw(l)
        ld.ellipse((160, y + 6, 204, y + 50), fill=CLAY + (255,))
        ld.text((173, y + 12), str(i + 1), font=F_CB, fill=WHITE + (255,))
        ld.text((230, y), head, font=F_M, fill=WHITE + (255,))
        ld.text((230, y + 48), body, font=F_D, fill=(200, 210, 225, 255))
        img.alpha_composite(fade(l, a))
    footer(d, dark=True)
    return img


# ── scene 2: serpentine pipeline ──
CW, CH = 415, 150
COLS = [130, 583, 1036, 1489]
ROWS = [250, 560]


def card_xy(i):
    r = 0 if i < 4 else 1
    c = i if i < 4 else 7 - i   # bottom row runs right to left
    return COLS[c], ROWS[r]


def scene2(t):
    img = Image.new("RGBA", (W, H), CREAM + (255,)); d = ImageDraw.Draw(img)
    ta = ease_out((t - S2) / 0.6)
    l = layer(); ld = ImageDraw.Draw(l)
    ld.text((140, 90), "How the call gets made", font=F_T, fill=NAVY + (255,))
    ld.text((140, 160), "Equity Analyst Agent (LLM: Claude).  Claude writes, Jev judges, code keeps score.", font=F_S, fill=GREY + (255,))
    img.alpha_composite(fade(l, ta))
    for i, (title, body, col) in enumerate(STEPS):
        t0 = STEP0 + i * STEP_DT
        if t < t0: continue
        a = ease_out((t - t0) / ENTER)
        x, y = card_xy(i); y += int((1 - a) * 24)
        l = layer(); ld = ImageDraw.Draw(l)
        tint = tuple(int(LIGHT[c] + (col[c] - LIGHT[c]) * 0.18) for c in range(3))
        ld.rounded_rectangle((x, y, x + CW, y + CH), radius=16, fill=tint + (255,), outline=col + (255,), width=4)
        ld.ellipse((x + 18, y + 18, x + 62, y + 62), fill=col + (255,))
        ld.text((x + 40 - 8 if i < 9 else x + 30, y + 27), str(i + 1), font=F_CB, fill=WHITE + (255,))
        ld.text((x + 76, y + 24), title, font=F_CB, fill=col + (255,))
        # body wrapped to two lines
        words = body.split(); lines = [""]
        for wd in words:
            if ld.textlength(lines[-1] + " " + wd, font=F_CD) > CW - 40: lines.append(wd)
            else: lines[-1] = (lines[-1] + " " + wd).strip()
        for k, ln in enumerate(lines[:3]):
            ld.text((x + 22, y + 74 + k * 26), ln, font=F_CD, fill=NAVY + (255,))
        img.alpha_composite(fade(l, a))
        # track to the next card with a travelling gold dot
        if i < 7:
            p = ease_io((t - (t0 + ENTER)) / (STEP_DT - ENTER))
            if p > 0:
                x1, y1 = card_xy(i); x2, y2 = card_xy(i + 1)
                if i == 3:   # down the right side
                    sx, sy, ex, ey = x1 + CW // 2, y1 + CH + 4, x2 + CW // 2, y2 - 4
                elif i < 3:
                    sx, sy, ex, ey = x1 + CW + 4, y1 + CH // 2, x2 - 4, y2 + CH // 2
                else:
                    sx, sy, ex, ey = x1 - 4, y1 + CH // 2, x2 + CW + 4, y2 + CH // 2
                cx, cy = sx + (ex - sx) * p, sy + (ey - sy) * p
                d.line((sx, sy, cx, cy), fill=NAVY, width=5)
                if p < 1: d.ellipse((cx - 9, cy - 9, cx + 9, cy + 9), fill=GOLD)
    # caption once all cards are in
    ca = ease_out((t - (STEP0 + 8 * STEP_DT)) / 0.5)
    if ca > 0:
        l = layer(); ld = ImageDraw.Draw(l)
        ld.text((140, 770), "Jev never writes. It reads the evidence and returns probabilities. The code turns those into the call.",
                font=F_D, fill=NAVY + (255,))
        img.alpha_composite(fade(l, ca))
    footer(d)
    return img


# ── scene 3: verdict ──
def scene3(t):
    img = Image.new("RGBA", (W, H), CREAM + (255,)); d = ImageDraw.Draw(img)
    u = t - S3
    d.text((140, 80), "Illustrative run: Eternal. Prices and targets withheld.", font=F_T, fill=NAVY)
    # left column: Claude's call, struck through
    a1 = ease_out(u / 0.5)
    l = layer(); ld = ImageDraw.Draw(l)
    ld.text((140, 220), "Claude's call", font=F_S, fill=GREY + (255,))
    ld.text((140, 262), "HOLD", font=F_BIG, fill=CLAY + (255,))
    img.alpha_composite(fade(l, a1))
    s = ease_out((u - 0.9) / 0.5)
    if s > 0:
        d.line((140, 318, 140 + int(320 * s), 318), fill=NAVY, width=10)
    a2 = ease_out((u - 1.4) / 0.5)
    if a2 > 0:
        l = layer(); ld = ImageDraw.Draw(l)
        ld.text((140, 420), "Thesis consistent with the figures: 26%", font=F_D, fill=NAVY + (255,))
        ld.text((140, 456), "So the feedback round fired.", font=F_D, fill=NAVY + (255,))
        img.alpha_composite(fade(l, a2))
    # middle: the two Jev scores
    a3 = ease_out((u - 2.0) / 0.5)
    if a3 > 0:
        l = layer(); ld = ImageDraw.Draw(l)
        ld.text((720, 220), "Jev's two judgments", font=F_S, fill=GREY + (255,))
        for k, (lab, val, mx, word) in enumerate([("Business quality", 0.7, 3, "average"), ("Price attractiveness", 0.0, 3, "expensive")]):
            y = 275 + k * 110
            ld.text((720, y), lab, font=F_CB, fill=NAVY + (255,))
            ld.rounded_rectangle((720, y + 40, 720 + 420, y + 62), radius=11, fill=LIGHT + (255,))
            g = ease_out((u - 2.2 - k * 0.3) / 0.8)
            ld.rounded_rectangle((720, y + 40, 720 + max(22, int(420 * (val / mx) * g)), y + 62), radius=11, fill=BLUE + (255,))
            ld.text((720 + 435, y + 36), f"{val * g:.1f} / {mx}  {word}", font=F_CD, fill=NAVY + (255,))
        ld.text((720, 500), "average business  x  expensive price  =", font=F_D, fill=NAVY + (255,))
        img.alpha_composite(fade(l, a3))
    # right: composed verdict stamp + bars
    a4 = ease_out((u - 3.2) / 0.5)
    if a4 > 0:
        l = layer(); ld = ImageDraw.Draw(l)
        pulse = 0.5 + 0.5 * math.sin((u - 3.2) * 2 * math.pi / 1.2)
        col = tuple(int(CLAY[c] + (GOLD[c] - CLAY[c]) * pulse * 0.5) for c in range(3))
        ld.rounded_rectangle((1330, 240, 1810, 380), radius=20, outline=col + (255,), width=6)
        ld.text((1362, 258), "REDUCE", font=F_BIG, fill=CLAY + (255,))
        ld.text((1360, 410), "63% probability  ·  confidence 0.53", font=F_D, fill=NAVY + (255,))
        ld.text((1360, 444), "80% interval SELL to REDUCE", font=F_D, fill=GREY + (255,))
        by = 520
        for lab, p in PROBS:
            g = ease_out((u - 3.4) / 1.0)
            ld.text((1330, by - 2), lab, font=F_CD, fill=NAVY + (255,))
            wpx = int(300 * p * g)
            ld.rectangle((1470, by, 1470 + max(wpx, 2), by + 16), fill=((CLAY if lab == "REDUCE" else BLUE) + (255,)))
            ld.text((1470 + wpx + 8, by - 2), f"{p * 100 * g:.0f}%", font=F_CD, fill=NAVY + (255,))
            by += 28
        img.alpha_composite(fade(l, a4))
    a5 = ease_out((u - 4.3) / 0.5)
    if a5 > 0:
        l = layer(); ld = ImageDraw.Draw(l)
        ld.text((140, 760), "Claude read the feedback and moved to REDUCE. Jev judged again and confirmed it.", font=F_M, fill=NAVY + (255,))
        ld.text((140, 810), "Reconciled fair value 24% below the price on Claude's own method weights.", font=F_D, fill=GREY + (255,))
        img.alpha_composite(fade(l, a5))
    footer(d)
    return img


# ── scene 4: closing ──
def scene4(t):
    img = Image.new("RGBA", (W, H), DARK + (255,)); d = ImageDraw.Draw(img)
    u = t - S4
    a = ease_out(u / 0.6)
    l = layer(); ld = ImageDraw.Draw(l)
    ld.text((160, 330), "Uncertainty becomes a number,", font=F_HOOK, fill=WHITE + (255,))
    ld.text((160, 420), "not an adjective.", font=F_HOOK, fill=GOLD + (255,))
    img.alpha_composite(fade(l, a))
    b = ease_out((u - 1.0) / 0.6)
    if b > 0:
        l = layer(); ld = ImageDraw.Draw(l)
        ld.text((160, 560), "A wide interval says the evidence is split before anyone sizes a trade.", font=F_HOOK2, fill=(200, 210, 225, 255))
        ld.text((160, 640), "Every decision is logged, so the calibration can be checked against what prices do.", font=F_D, fill=(150, 165, 185, 255))
        img.alpha_composite(fade(l, b))
    footer(d, dark=True)
    return img


def frame(t):
    if CORE:
        if t < S3 - XF: return scene2(t).convert("RGB")
        if t < S3:      return Image.blend(scene2(t).convert("RGB"), scene3(t).convert("RGB"), (t - (S3 - XF)) / XF)
        return scene3(t).convert("RGB")
    if t < S2 - XF: return scene1(t).convert("RGB")
    if t < S2:      return Image.blend(scene1(t).convert("RGB"), scene2(t).convert("RGB"), (t - (S2 - XF)) / XF)
    if t < S3 - XF: return scene2(t).convert("RGB")
    if t < S3:      return Image.blend(scene2(t).convert("RGB"), scene3(t).convert("RGB"), (t - (S3 - XF)) / XF)
    if t < S4 - XF: return scene3(t).convert("RGB")
    if t < S4:      return Image.blend(scene3(t).convert("RGB"), scene4(t).convert("RGB"), (t - (S4 - XF)) / XF)
    return scene4(t).convert("RGB")


SLOW = float(sys.argv[2]) if len(sys.argv) > 2 else 1.6   # 1.0 = original pace; 1.6 = 60% slower
tmp = OUT.with_name("_raw_" + OUT.name)
vw = cv2.VideoWriter(str(tmp), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H))
for f in range(int(T_END * SLOW * FPS)):
    vw.write(cv2.cvtColor(np.array(frame(f / FPS / SLOW)), cv2.COLOR_RGB2BGR))
vw.release()
subprocess.run([FF, "-y", "-loglevel", "error", "-i", str(tmp), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-movflags", "+faststart", str(OUT)], check=True)
tmp.unlink()
print(f"wrote {OUT} ({OUT.stat().st_size:,} bytes, {T_END * SLOW:.1f}s, {W}x{H}, pace x{1/SLOW:.2f})")
