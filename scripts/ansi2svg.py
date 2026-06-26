#!/usr/bin/env python3
"""
ansi2svg.py — wandelt einen ANSI-Truecolor-Terminal-Stream (von stdin) in eine
Terminal-Screenshot-SVG (auf stdout) um. stdlib only.

GitHub rendert keine ANSI-Farben in Markdown — diese SVG macht das echte,
farbige memDash-Dashboard im README sichtbar.

Unterstützte Sequenzen:
  \\033[38;2;r;g;b m   Vordergrund (truecolor)
  \\033[48;2;r;g;b m   Hintergrund (truecolor)
  \\033[1m             bold
  \\033[2m             dim  (fg auf ~55% Helligkeit gemischt)
  \\033[0m / \\033[m    reset
Andere SGR-Codes werden unauffällig ignoriert.

Aufruf:  ... | python3 scripts/ansi2svg.py > out.svg
"""
from __future__ import annotations

import re
import sys

# ── Palette / Layout (konsistent mit src/markmem/core/dashboard.py) ──────────
BG = (18, 22, 28)        # _DUNKEL
DEFAULT_FG = (230, 236, 246)  # TEXT
DIM_MIX = 0.55           # dim → fg auf ~55% Helligkeit

CHAR_W = 8.6             # Zeichenbreite (monospace) — Boxen/Balken fluchten
LINE_H = 20.0            # Zeilenhöhe
PAD_X = 18.0
PAD_TOP = 40.0           # Platz für Window-Dots
PAD_BOT = 16.0
FONT_SIZE = 14
FONT = "ui-monospace,'JetBrains Mono','DejaVu Sans Mono',monospace"

SGR_RE = re.compile(r"\033\[([0-9;]*)m")


def mix(c, t, f):
    """Mischt Farbe c Richtung Ziel t mit Faktor f (0..1)."""
    return tuple(round(c[i] + (t[i] - c[i]) * f) for i in range(3))


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def rgb(c) -> str:
    return f"rgb({c[0]},{c[1]},{c[2]})"


class Style:
    __slots__ = ("fg", "bg", "bold", "dim")

    def __init__(self):
        self.fg = None     # None = default fg
        self.bg = None     # None = transparent
        self.bold = False
        self.dim = False

    def copy(self):
        s = Style()
        s.fg, s.bg, s.bold, s.dim = self.fg, self.bg, self.bold, self.dim
        return s

    def key(self):
        return (self.fg, self.bg, self.bold, self.dim)


def apply_sgr(style: Style, params: str) -> Style:
    """Wendet einen SGR-Parametersatz an, gibt neuen Style zurück."""
    s = style.copy()
    # leerer Parameter == reset
    nums = [p for p in params.split(";")] if params else [""]
    i = 0
    while i < len(nums):
        tok = nums[i]
        n = int(tok) if tok.isdigit() else 0
        if tok == "" or n == 0:        # reset
            s = Style()
        elif n == 1:
            s.bold = True
        elif n == 2:
            s.dim = True
        elif n == 22:
            s.bold = False
            s.dim = False
        elif n == 39:
            s.fg = None
        elif n == 49:
            s.bg = None
        elif n in (38, 48):            # 38;2;r;g;b oder 48;2;r;g;b
            mode = int(nums[i + 1]) if i + 1 < len(nums) and nums[i + 1].isdigit() else 0
            if mode == 2 and i + 4 < len(nums):
                r, g, b = (int(nums[i + 2]), int(nums[i + 3]), int(nums[i + 4]))
                if n == 38:
                    s.fg = (r, g, b)
                else:
                    s.bg = (r, g, b)
                i += 4
            elif mode == 5 and i + 2 < len(nums):
                i += 2                 # 256-Farben unbenutzt im Dashboard → überspringen
        # andere Codes: unauffällig ignorieren
        i += 1
    return s


def parse_line(line: str):
    """Zerlegt eine Zeile in (text, Style)-Runs. Verlangt Start-Style via globalem Carry."""
    runs = []
    pos = 0
    style = parse_line.carry
    for m in SGR_RE.finditer(line):
        if m.start() > pos:
            runs.append((line[pos:m.start()], style))
        style = apply_sgr(style, m.group(1))
        pos = m.end()
    if pos < len(line):
        runs.append((line[pos:], style))
    parse_line.carry = style   # Stil über Zeilengrenze tragen (selten nötig, aber korrekt)
    return runs


parse_line.carry = Style()


def main():
    data = sys.stdin.buffer.read().decode("utf-8", "replace")
    # Carriage Returns / Tabs grob normalisieren
    data = data.replace("\r\n", "\n").replace("\r", "").replace("\t", "    ")
    raw_lines = data.split("\n")
    # abschließende Leerzeile entfernen
    while raw_lines and raw_lines[-1] == "":
        raw_lines.pop()
    if not raw_lines:
        raw_lines = [""]

    parse_line.carry = Style()
    parsed = [parse_line(ln) for ln in raw_lines]

    # max. sichtbare Zeilenbreite (in Zeichen) ohne ANSI
    def visible_len(runs):
        return sum(len(t) for t, _ in runs)

    max_cols = max((visible_len(r) for r in parsed), default=1)
    n_lines = len(parsed)

    width = PAD_X * 2 + max_cols * CHAR_W
    height = PAD_TOP + n_lines * LINE_H + PAD_BOT
    W = round(width)
    H = round(height)

    out = []
    out.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
        f'width="{W}" height="{H}" font-family="{FONT}" '
        f'font-size="{FONT_SIZE}" role="img" aria-label="memDash Terminal-Screenshot">'
    )
    # Hintergrund (abgerundet)
    out.append(f'<rect x="0" y="0" width="{W}" height="{H}" rx="10" ry="10" fill="{rgb(BG)}"/>')
    # dünne Titelleiste-Trennung (sehr dezent)
    out.append(
        f'<rect x="0" y="0" width="{W}" height="30" rx="10" ry="10" '
        f'fill="rgb(24,29,37)"/>'
    )
    out.append(f'<rect x="0" y="20" width="{W}" height="10" fill="rgb(24,29,37)"/>')
    # Window-Dots (dezent: rot/gelb/grün)
    for cx, col in ((18, "rgb(190,80,80)"), (34, "rgb(190,160,70)"), (50, "rgb(80,170,110)")):
        out.append(f'<circle cx="{cx}" cy="15" r="5" fill="{col}"/>')

    # Hintergrund-Rechtecke je Run mit bg (erst zeichnen, damit Text darüber liegt)
    char_h = LINE_H
    for li, runs in enumerate(parsed):
        y_top = PAD_TOP + li * LINE_H - 14  # obere Kante der Textzeile
        col = 0
        for text, st in runs:
            if st.bg is not None:
                x = PAD_X + col * CHAR_W
                w = len(text) * CHAR_W
                out.append(
                    f'<rect x="{x:.1f}" y="{y_top:.1f}" width="{w:.1f}" '
                    f'height="{char_h:.1f}" fill="{rgb(st.bg)}"/>'
                )
            col += len(text)

    # Text-Runs
    for li, runs in enumerate(parsed):
        y = PAD_TOP + li * LINE_H
        spans = []
        col = 0
        for text, st in runs:
            if text == "":
                continue
            fg = st.fg if st.fg is not None else DEFAULT_FG
            if st.dim:
                fg = mix(fg, BG, 1 - DIM_MIX)  # Richtung Hintergrund → ~55% Helligkeit
            x = PAD_X + col * CHAR_W
            weight = ' font-weight="700"' if st.bold else ""
            # xml:space + feste x je Span hält monospace-Ausrichtung
            spans.append(
                f'<tspan x="{x:.1f}" fill="{rgb(fg)}"{weight}>{esc(text)}</tspan>'
            )
            col += len(text)
        if spans:
            out.append(
                f'<text y="{y:.1f}" xml:space="preserve" '
                f'dominant-baseline="alphabetic">{"".join(spans)}</text>'
            )

    out.append("</svg>")
    sys.stdout.write("\n".join(out) + "\n")


if __name__ == "__main__":
    main()
