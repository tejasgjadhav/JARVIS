"""Animated infographic for the Jev integration (LinkedIn 4:5, 1080x1350, H.264).

Steps start hidden and enter one by one; a dot travels down the connector; the
result bars grow with easing; the final call pulses; the disclaimer stays in the
footer throughout. Prices and targets are withheld (covered-person rule).

Usage: python3 tools/jev_flow_video.py ~/Downloads/Equity_Analyst_Agent_Jev_Flow.mp4
"""
import math
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

OUT = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else Path("~/Downloads/Equity_Analyst_Agent_Jev_Flow.mp4").expanduser()
FF = "/Users/sayali/Library/Python/3.9/lib/python/site-packages/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v7.1"
W, H, FPS = 1080, 1350, 30
CREAM = (243, 238, 228); NAVY = (11, 31, 58); CLAY = (206, 100, 64); BLUE = (27, 111, 179)
GREY = (107, 122, 141); WHITE = (255, 255, 255); LIGHT = (226, 232, 240); GOLD = (222, 168, 60)


def font(sz, bold=False):
    return ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold
                              else "/System/Library/Fonts/Supplemental/Arial.ttf", sz)


F_T = font(46, True); F_S = font(25); F_B = font(27, True); F_D = font(22); F_K = font(25, True)
F_F = font(21); F_X = font(17); F_N = font(40, True)

STEPS = [
    ("You ask", '"Should I buy Eternal?"', CLAY),
    ("The agent pulls live numbers", "Price, P/E, growth, margins, cash flow, analyst targets", NAVY),
    ("Claude writes the note and weights the methods", "Thesis, cases, DCF assumptions, a weight per valuation method", CLAY),
    ("The agent reconciles value", "DCF, comps, SOTP, scenarios, the street: one weighted fair value", NAVY),
    ("Jev judges the business and the price separately", "Two 0-3 scores; code composes the call from both", BLUE),
    ("Claude revises, only if Jev disagrees or a check fails", "Reconcile the call with the numbers, or defend it with figures", CLAY),
    ("Jev judges again: the final call", "Verdict, confidence, 80% interval, sizing guidance", BLUE),
    ("You get the decision", "Chat, voice, Excel, PDF, and a logged trail for calibration", CLAY),
]
PROBS = [("SELL", 0.37), ("REDUCE", 0.63), ("HOLD", 0.00), ("ACCUMULATE", 0.00), ("BUY", 0.00)]
N = len(STEPS); TOP = 170; BH = 82; GAP = 14; X0 = 80; BW = W - 2 * X0

# ── timeline (seconds) ──
T_TITLE = 0.0        # title types itself over 1.0s
T_STEP0 = 1.3        # first step enters
STEP_DT = 0.85       # gap between steps
ENTER = 0.45         # slide/fade duration
T_PANEL = T_STEP0 + N * STEP_DT + 0.2
T_BARS = T_PANEL + 0.5
T_PULSE = T_BARS + 1.4
T_END = T_PULSE + 4.0


def ease_out(x):
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


def ease_in_out(x):
    x = max(0.0, min(1.0, x))
    return 0.5 - 0.5 * math.cos(math.pi * x)


def step_y(i):
    return TOP + i * (BH + GAP)


def frame(t):
    img = Image.new("RGBA", (W, H), CREAM + (255,))
    d = ImageDraw.Draw(img)

    # title: typewriter
    title = "How Jev helps in equity analysis"
    k = ease_out((t - T_TITLE) / 1.0)
    shown = title[: int(len(title) * k)]
    d.text((X0, 50), shown, font=F_T, fill=NAVY)
    if k < 1 and int(t * 6) % 2 == 0:
        tw = d.textlength(shown, font=F_T)
        d.rectangle((X0 + tw + 4, 54, X0 + tw + 8, 96), fill=CLAY)
    sub_a = ease_out((t - 0.9) / 0.5)
    if sub_a > 0:
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0)); ld = ImageDraw.Draw(layer)
        ld.text((X0, 108), "Equity Analyst Agent (LLM: Claude). Claude writes, Jev judges, code keeps score.",
                font=F_S, fill=GREY + (int(255 * sub_a),))
        img.alpha_composite(layer)

    # steps: enter one by one
    for i, (title_i, body, col) in enumerate(STEPS):
        t0 = T_STEP0 + i * STEP_DT
        if t < t0:
            continue
        a = ease_out((t - t0) / ENTER)
        y = step_y(i) + int((1 - a) * 28)
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0)); ld = ImageDraw.Draw(layer)
        tint = tuple(int(LIGHT[c] + (col[c] - LIGHT[c]) * 0.18) for c in range(3))
        ld.rounded_rectangle((X0, y, X0 + BW, y + BH), radius=14, fill=tint + (255,), outline=col + (255,), width=4)
        ld.text((X0 + 22, y + 9), f"{i + 1}. {title_i}", font=F_B, fill=col + (255,))
        ld.text((X0 + 22, y + 46), body, font=F_D, fill=NAVY + (255,))
        alpha = layer.getchannel("A").point(lambda v: int(v * a))
        layer.putalpha(alpha)
        img.alpha_composite(layer)
        # connector to the next step, drawn while the dot travels
        if i < N - 1:
            t1 = t0 + ENTER
            p = ease_in_out((t - t1) / (STEP_DT - ENTER))
            if p > 0:
                y_from = step_y(i) + BH + 2; y_to = step_y(i) + BH + GAP - 3
                d.line((W // 2, y_from, W // 2, y_from + (y_to - y_from) * p), fill=NAVY, width=4)
                if p < 1:
                    cy = y_from + (y_to - y_from) * p
                    d.ellipse((W // 2 - 7, cy - 7, W // 2 + 7, cy + 7), fill=GOLD)

    # result panel
    pa = ease_out((t - T_PANEL) / 0.5)
    if pa > 0:
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0)); ld = ImageDraw.Draw(layer)
        py = step_y(N - 1) + BH + 16
        ld.rounded_rectangle((X0, py, X0 + BW, H - 96), radius=14, fill=WHITE + (255,), outline=BLUE + (255,), width=3)
        ld.text((X0 + 22, py + 10), "Illustrative run: Eternal (Indian consumer internet). Prices withheld.", font=F_K, fill=NAVY + (255,))
        ld.text((X0 + 22, py + 44), "Reconciled fair value 24% below price. Average business x expensive price = REDUCE 63%, confidence 0.53.",
                font=F_X, fill=BLUE + (255,))
        bx = X0 + 22; by = py + 80
        g = ease_out((t - T_BARS) / 1.0)
        for lab, pval in PROBS:
            ld.text((bx, by - 3), lab, font=F_F, fill=NAVY + (255,))
            wpx = int(600 * pval * g)
            fillc = (BLUE if lab != "REDUCE" else CLAY) + (255,)
            ld.rectangle((bx + 150, by, bx + 150 + max(wpx, 2), by + 16), fill=fillc)
            ld.text((bx + 150 + wpx + 8, by - 3), f"{pval * 100 * g:.0f}%", font=F_F, fill=NAVY + (255,))
            by += 26
        ld.text((X0 + 22, H - 124), "Claude said HOLD. Jev disagreed, Claude revised to REDUCE, Jev confirmed. Price and targets withheld.",
                font=F_X, fill=GREY + (255,))
        alpha = layer.getchannel("A").point(lambda v: int(v * pa))
        layer.putalpha(alpha)
        img.alpha_composite(layer)
        # pulse on the final-call box (step 7) after the bars land
        if t >= T_PULSE:
            pulse = 0.5 + 0.5 * math.sin((t - T_PULSE) * 2 * math.pi / 1.2)
            y7 = step_y(6)
            d.rounded_rectangle((X0 - 4, y7 - 4, X0 + BW + 4, y7 + BH + 4), radius=17,
                                outline=tuple(int(BLUE[c] + (GOLD[c] - BLUE[c]) * pulse) for c in range(3)), width=4)
            # big verdict stamp
            sa = ease_out((t - T_PULSE) / 0.4)
            layer = Image.new("RGBA", (W, H), (0, 0, 0, 0)); ld = ImageDraw.Draw(layer)
            ld.text((X0 + BW - 250, py + 150), "REDUCE", font=F_N, fill=CLAY + (255,))
            ld.text((X0 + BW - 250, py + 196), "63% · conf 0.53", font=F_F, fill=NAVY + (255,))
            ld.text((X0 + BW - 250, py + 222), "80% interval SELL–REDUCE", font=F_X, fill=GREY + (255,))
            alpha = layer.getchannel("A").point(lambda v: int(v * sa))
            layer.putalpha(alpha)
            img.alpha_composite(layer)

    # footer: disclaimer + byline, always on
    d.text((X0, H - 84), "Personal project, illustrative and educational. Not investment advice or a recommendation. Views my own,", font=F_X, fill=GREY)
    d.text((X0, H - 62), "not my employer's, who has not reviewed this. No holding or intended trade is implied. Model outputs can be wrong.", font=F_X, fill=GREY)
    d.text((X0, H - 34), "Tejas Jadhav, CFA, FRM", font=F_K, fill=CLAY)
    d.text((W - X0 - 420, H - 32), "Jev is a TypeSafe System One model", font=F_F, fill=GREY)
    return img.convert("RGB")


tmp = OUT.with_name("_raw_" + OUT.name)
vw = cv2.VideoWriter(str(tmp), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H))
for f in range(int(T_END * FPS)):
    vw.write(cv2.cvtColor(np.array(frame(f / FPS)), cv2.COLOR_RGB2BGR))
vw.release()
frame(T_END - 0.1).save(OUT.with_name(OUT.stem + "_still.png"))
subprocess.run([FF, "-y", "-loglevel", "error", "-i", str(tmp), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-movflags", "+faststart", str(OUT)], check=True)
tmp.unlink()
print(f"wrote {OUT} ({OUT.stat().st_size:,} bytes, {T_END:.1f}s)")
