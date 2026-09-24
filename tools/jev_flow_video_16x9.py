"""Flow chart plus results, fitted to a 16:9 frame (1920x1080).

Eight cards down the left, entering one by one with a gold dot on the
connector; the Eternal result panel on the right fades in after the last
card, bars grow, the verdict stamps in. Prices withheld. Disclaimer on.

Usage: python3 tools/jev_flow_video_16x9.py ~/Downloads/Equity_Analyst_Agent_Jev_Flow_16x9.mp4
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


def font(sz, bold=False):
    return ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold
                              else "/System/Library/Fonts/Supplemental/Arial.ttf", sz)


F_T = font(40, True); F_S = font(22); F_B = font(25, True); F_D = font(20); F_X = font(16); F_K = font(24, True); F_F = font(19)
F_P = font(24, True); F_PD = font(19); F_BIG = font(84, True)
PROBS = [("SELL", 0.37), ("REDUCE", 0.63), ("HOLD", 0.00), ("ACCUMULATE", 0.00), ("BUY", 0.00)]

STEPS = [
    ("You ask", '"Should I buy Eternal?"', CLAY),
    ("The agent pulls live numbers", "Price, P/E, growth, margins, cash flow, analyst targets", NAVY),
    ("Claude writes the note and weights the methods", "Thesis, bull and bear cases, DCF assumptions, a weight per valuation method", CLAY),
    ("The agent reconciles value", "DCF, peer comps, SOTP, scenarios, the street: one weighted fair value", NAVY),
    ("Jev judges the business and the price separately", "Two 0-3 scores with their own probability spreads; code composes the call from both", BLUE),
    ("Claude revises, only if Jev disagrees or a check fails", "Reconcile the call with the numbers, or defend it with figures", CLAY),
    ("Jev judges again: the final call", "Verdict, confidence, 80% interval, sizing guidance", BLUE),
    ("You get the decision", "Chat, voice, Excel, PDF, and a logged trail for calibration", CLAY),
]
N = len(STEPS)
CW = 1120; X0 = 90; TOP = 130; BH = 88; GAP = 16
PX = X0 + CW + 50; PW = W - PX - 90
T0 = 0.8; DT = 0.8; ENTER = 0.4; T_PANEL = T0 + N * DT + 0.2; T_BARS = T_PANEL + 0.5; T_STAMP = T_BARS + 1.2; T_END = T_STAMP + 3.5


def ease_out(x):
    x = max(0.0, min(1.0, x)); return 1 - (1 - x) ** 3


def ease_io(x):
    x = max(0.0, min(1.0, x)); return 0.5 - 0.5 * math.cos(math.pi * x)


def frame(t):
    img = Image.new("RGBA", (W, H), CREAM + (255,)); d = ImageDraw.Draw(img)
    ta = ease_out(t / 0.6)
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0)); ld = ImageDraw.Draw(lay)
    ld.text((X0, 34), "How Jev helps in equity analysis", font=F_T, fill=NAVY + (int(255 * ta),))
    ld.text((X0, 84), "Equity Analyst Agent (LLM: Claude).  Claude writes, Jev judges, code keeps score.", font=F_S, fill=GREY + (int(255 * ta),))
    img.alpha_composite(lay)
    for i, (title, body, col) in enumerate(STEPS):
        t0 = T0 + i * DT
        if t < t0: continue
        a = ease_out((t - t0) / ENTER)
        y = TOP + i * (BH + GAP) + int((1 - a) * 22)
        lay = Image.new("RGBA", (W, H), (0, 0, 0, 0)); ld = ImageDraw.Draw(lay)
        tint = tuple(int(LIGHT[c] + (col[c] - LIGHT[c]) * 0.18) for c in range(3))
        ld.rounded_rectangle((X0, y, X0 + CW, y + BH), radius=14, fill=tint + (255,), outline=col + (255,), width=4)
        ld.ellipse((X0 + 18, y + 22, X0 + 62, y + 66), fill=col + (255,))
        ld.text((X0 + 32, y + 30), str(i + 1), font=F_B, fill=WHITE + (255,))
        ld.text((X0 + 80, y + 14), title, font=F_B, fill=col + (255,))
        ld.text((X0 + 80, y + 50), body, font=F_D, fill=NAVY + (255,))
        lay.putalpha(lay.getchannel("A").point(lambda v: int(v * a)))
        img.alpha_composite(lay)
        if i < N - 1:
            p = ease_io((t - (t0 + ENTER)) / (DT - ENTER))
            if p > 0:
                y1 = TOP + i * (BH + GAP) + BH + 2; y2 = y1 + GAP - 4
                cy = y1 + (y2 - y1) * p
                d.line((W // 2, y1, W // 2, cy), fill=NAVY, width=5)
                if p < 1: d.ellipse((W // 2 - 8, cy - 8, W // 2 + 8, cy + 8), fill=GOLD)
    # ── result panel on the right ──
    pa = ease_out((t - T_PANEL) / 0.5)
    if pa > 0:
        lay = Image.new("RGBA", (W, H), (0, 0, 0, 0)); ld = ImageDraw.Draw(lay)
        py = TOP; pb = TOP + N * (BH + GAP) - GAP
        ld.rounded_rectangle((PX, py, PX + PW, pb), radius=16, fill=WHITE + (255,), outline=BLUE + (255,), width=3)
        ld.text((PX + 26, py + 22), "Illustrative run: Eternal", font=F_P, fill=NAVY + (255,))
        ld.text((PX + 26, py + 56), "Prices and targets withheld", font=F_PD, fill=GREY + (255,))
        ld.text((PX + 26, py + 104), "Claude's call: HOLD", font=F_PD, fill=NAVY + (255,))
        ld.text((PX + 26, py + 132), "Thesis consistent with the figures: 26%", font=F_PD, fill=NAVY + (255,))
        ld.text((PX + 26, py + 160), "So the feedback round fired.", font=F_PD, fill=NAVY + (255,))
        g = ease_out((t - T_BARS) / 1.0)
        ld.text((PX + 26, py + 208), "Jev: average business x expensive price", font=F_PD, fill=BLUE + (255,))
        by = py + 246
        for lab, pv in PROBS:
            ld.text((PX + 26, by - 2), lab, font=F_PD, fill=NAVY + (255,))
            wpx = int((PW - 250) * pv * g)
            ld.rectangle((PX + 160, by, PX + 160 + max(wpx, 2), by + 16), fill=((CLAY if lab == "REDUCE" else BLUE) + (255,)))
            ld.text((PX + 160 + wpx + 8, by - 2), f"{pv * 100 * g:.0f}%", font=F_PD, fill=NAVY + (255,))
            by += 30
        sa = ease_out((t - T_STAMP) / 0.4)
        if sa > 0:
            pulse = 0.5 + 0.5 * math.sin((t - T_STAMP) * 2 * math.pi / 1.2)
            col = tuple(int(CLAY[c] + (GOLD[c] - CLAY[c]) * pulse * 0.5) for c in range(3))
            ld.rounded_rectangle((PX + 26, by + 18, PX + PW - 26, by + 128), radius=16, outline=col + (int(255 * sa),), width=5)
            ld.text((PX + 44, by + 26), "REDUCE", font=F_BIG, fill=CLAY + (int(255 * sa),))
            ld.text((PX + 26, by + 146), "63% probability  ·  confidence 0.53", font=F_PD, fill=NAVY + (int(255 * sa),))
            ld.text((PX + 26, by + 174), "80% interval SELL to REDUCE", font=F_PD, fill=GREY + (int(255 * sa),))
            ld.text((PX + 26, by + 202), "Reconciled fair value 24% below price", font=F_PD, fill=GREY + (int(255 * sa),))
            ld.text((PX + 26, by + 230), "Claude revised to REDUCE. Jev confirmed.", font=F_PD, fill=NAVY + (int(255 * sa),))
        lay.putalpha(lay.getchannel("A").point(lambda v: int(v * pa)))
        img.alpha_composite(lay)
    d.text((X0, H - 78), "Personal project, illustrative and educational. Not investment advice or a recommendation. Views my own, not my employer's, "
                         "who has not reviewed this. No holding or intended trade is implied. Model outputs can be wrong.", font=F_X, fill=GREY)
    d.text((X0, H - 50), "Tejas Jadhav, CFA, FRM", font=F_K, fill=CLAY)
    d.text((W - 90 - 330, H - 46), "Jev is a TypeSafe System One model", font=F_F, fill=GREY)
    return img.convert("RGB")


tmp = OUT.with_name("_raw_" + OUT.name)
vw = cv2.VideoWriter(str(tmp), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H))
for f in range(int(T_END * FPS)):
    vw.write(cv2.cvtColor(np.array(frame(f / FPS)), cv2.COLOR_RGB2BGR))
vw.release()
frame(T_END - 0.1).save(OUT.with_suffix(".png"))
subprocess.run([FF, "-y", "-loglevel", "error", "-i", str(tmp), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-movflags", "+faststart", str(OUT)], check=True)
tmp.unlink()
print(f"wrote {OUT} ({OUT.stat().st_size:,} bytes, {T_END:.1f}s, {W}x{H})")
