"""
tests/test_dashboard_breite.py — Kern-Garantie des responsiven Dashboards:

Für mehrere Terminal-Breiten (COLUMNS) darf KEINE sichtbare Zeile breiter sein als
COLUMNS. Gemessen wird die Unicode-Zellbreite OHNE ANSI-Escapes — exakt über die
Modul-Funktion ``dashboard.zellbreite`` (nutzt intern wcwidth bzw. east-asian-Fallback).

Zusätzlich: ``MEMDASH_FARBEN=aus`` darf nicht crashen (Farb-Degradation bis „keine
Farbe"). ``MEMDASH_INTRO=aus`` ist gesetzt (keine Animation, kein TTY-Bedarf).

render() schreibt nach stdout; wir fangen es ab und prüfen Zeile für Zeile.
"""
from __future__ import annotations

import io
from contextlib import redirect_stdout

import pytest

BREITEN = [120, 80, 56, 44, 30]


def _render_einfangen(monkeypatch, columns: int, farben: str | None = None) -> list[str]:
    from markmem.core import dashboard

    monkeypatch.setenv("COLUMNS", str(columns))
    monkeypatch.setenv("LINES", "40")
    monkeypatch.setenv("MEMDASH_INTRO", "aus")
    if farben is not None:
        monkeypatch.setenv("MEMDASH_FARBEN", farben)

    buf = io.StringIO()
    with redirect_stdout(buf):
        dashboard.render()
    return buf.getvalue().splitlines()


@pytest.mark.parametrize("columns", BREITEN)
def test_keine_zeile_breiter_als_columns(monkeypatch, columns):
    from markmem.core import dashboard

    zeilen = _render_einfangen(monkeypatch, columns)
    assert zeilen, "render() sollte Ausgabe erzeugen"

    # terminalgroesse() erzwingt min. 20 Spalten — die effektive Render-Breite ist
    # also max(20, columns). Genau gegen diese Breite prüfen.
    effektiv = max(20, columns)
    zu_breit = []
    for z in zeilen:
        b = dashboard.zellbreite(z)  # strippt ANSI intern + misst Zellbreite
        if b > effektiv:
            zu_breit.append((b, dashboard.ohne_ansi(z)))
    assert not zu_breit, (
        f"COLUMNS={columns}: {len(zu_breit)} Zeile(n) zu breit (> {effektiv}): "
        + "; ".join(f"[{b}] {t!r}" for b, t in zu_breit[:5])
    )


@pytest.mark.parametrize("columns", BREITEN)
def test_farben_aus_kein_crash_und_kein_ansi(monkeypatch, columns):
    from markmem.core import dashboard

    # Kernaussage: FARBEN=aus crasht nicht und rendert Ausgabe.
    zeilen = _render_einfangen(monkeypatch, columns, farben="aus")
    assert zeilen
    # Farb-Sequenzen (38;/48; SGR-Farbcodes) müssen weg sein; reine BOLD/RST-Marker
    # (\033[1m / \033[0m) erzeugt der Box-Rahmen ggf. noch — sie zählen dank
    # ANSI-Strip nicht zur Breite und sind kein Farb-Leak.
    roh = "\n".join(zeilen)
    assert "\033[38;" not in roh and "\033[48;" not in roh, "FARBEN=aus sollte keine Farb-SGR enthalten"
    # Breiten-Garantie gilt auch farblos.
    effektiv = max(20, columns)
    for z in zeilen:
        assert dashboard.zellbreite(z) <= effektiv


def test_zellbreite_funktion_grundlagen(monkeypatch):
    from markmem.core import dashboard

    assert dashboard.zellbreite("abc") == 3
    # ANSI wird gestrippt → zählt nicht zur Breite.
    assert dashboard.zellbreite("\033[31mabc\033[0m") == 3
    # Ostasiatische Vollbreite zählt doppelt (≥ Länge in Codepoints).
    assert dashboard.zellbreite("漢字") >= 4
