#!/usr/bin/env bash
#
# privacy_check.sh — Privacy-/Identitäts-Gate für das markmem-Repo.
#
# Zweck: Verhindert, dass identitätsnahe oder umgebungsspezifische Spuren ins
# öffentliche Paket gelangen. Läuft über die GETRACKTEN Dateien (git ls-files),
# nie über .git/ und nie über untracked Müll. Exit != 0 bei JEDEM Treffer, damit
# das CI-Gate blockiert. Bei sauberem Stand: "privacy: clean" + Exit 0.
#
# Geprüft wird auf:
#   1. Absoluter Pfad "/root/"            — VPS-spezifischer Home-Pfad.
#   2. "NEO849"                            — privater GitHub-/Backup-Namespace.
#   3. "cypherneo" (case-insensitive)      — Researcher-Handle.
#   4. Identitätsnahe Tags                 — yormas | neo-portfolio | freelance-pentest.
#   5. "bugbounty" als PFAD-Leak           — Domänen-Leak in Pfadform (z.B. ~/bugbounty/,
#      AUSSERHALB von examples/profiles/      bugbounty/targets, /bugbounty). Der reine
#      und docs/                              Profil-NAME `bugbounty` (Feature) ist überall
#                                            erlaubt; in examples/profiles/ + docs/ ist auch
#                                            jede Erwähnung legitim.
#   6. Echte Memory-Karten ohne ".sample"  — in examples/memory/ darf jede *.md-Karte nur
#      -Infix                                als anonymisiertes Sample liegen; Ausnahme:
#                                            die Tier-Indizes MEMORY.md/MEMORY_DEEP.md/
#                                            MEMORY_INFRA.md und auto-generierte Register.
#
# Robust: keine Abhängigkeit außer git + grep. Deutsch kommentiert.

set -euo pipefail

# In die Repo-Wurzel wechseln (Skript darf von überall gestartet werden).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# Liste der getrackten Dateien (NUL-getrennt → robust gegen Leerzeichen).
# Fallback auf find, falls (unwahrscheinlich) kein git-Repo vorliegt.
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    mapfile -d '' FILES < <(git ls-files -z)
else
    mapfile -d '' FILES < <(find . -type f -not -path './.git/*' -print0)
fi

FAIL=0       # Treffer-Zähler
treffer() {  # treffer <beschreibung> <datei> <zeile/details>
    echo "PRIVACY-TREFFER: $1"
    echo "  → $2"
    [ -n "${3:-}" ] && echo "    $3"
    FAIL=1
}

# Diese Datei selbst (das Gate) enthält die Suchmuster als Literale → ausschließen,
# sonst meldet es sich selbst. Pfad relativ zur Repo-Wurzel.
SELF="scripts/privacy_check.sh"

# ── Mustergruppe A: überall verboten ────────────────────────────────────────────
# Feste Strings (grep -F wäre möglich, aber wir wollen case-insensitive für manche).
for f in "${FILES[@]}"; do
    # Binärdateien überspringen (grep -I).
    [ -f "$f" ] || continue
    [ "$f" = "$SELF" ] && continue

    # 1. /root/
    if grep -InF '/root/' -- "$f" >/dev/null 2>&1; then
        treffer "absoluter Pfad /root/" "$f" "$(grep -InF '/root/' -- "$f" | head -1)"
    fi
    # 2. NEO849
    if grep -InF 'NEO849' -- "$f" >/dev/null 2>&1; then
        treffer "Namespace NEO849" "$f" "$(grep -InF 'NEO849' -- "$f" | head -1)"
    fi
    # 3. cypherneo (case-insensitive)
    if grep -Iin 'cypherneo' -- "$f" >/dev/null 2>&1; then
        treffer "Handle cypherneo" "$f" "$(grep -Iin 'cypherneo' -- "$f" | head -1)"
    fi
    # 4. identitätsnahe Tags (case-insensitive)
    if grep -IinE 'yormas|neo-portfolio|freelance-pentest' -- "$f" >/dev/null 2>&1; then
        treffer "identitätsnaher Tag" "$f" "$(grep -IinE 'yormas|neo-portfolio|freelance-pentest' -- "$f" | head -1)"
    fi
done

# ── Mustergruppe B: "bugbounty" als PFAD-Leak außerhalb erlaubter Pfade ───────────
# Der Profil-NAME `bugbounty` ist ein legitimes öffentliches Feature (README/CHANGELOG/
# Code/Tests referenzieren ihn). Geleakt ist nur die PFADFORM aus der Ursprungs-Umgebung,
# z.B. "~/bugbounty/", "bugbounty/targets", "/bugbounty/...". Genau die fangen wir:
# "bugbounty" unmittelbar gefolgt von "/" (Verzeichnis-Leak, z.B. bugbounty/targets)
# ODER mit vorangestelltem "~" (Home-Leak, ~/bugbounty). NICHT erfasst: der legitime
# Profil-Dateipfad examples/profiles/bugbounty.toml (kein "/" NACH bugbounty).
# In examples/profiles/ + docs/ ist ohnehin alles erlaubt.
BB_PFAD_RE='(~/?bugbounty|bugbounty/)'
for f in "${FILES[@]}"; do
    [ -f "$f" ] || continue
    [ "$f" = "$SELF" ] && continue
    case "$f" in
        examples/profiles/*|docs/*) continue ;;  # legitime Vorkommen
    esac
    if grep -IinE "$BB_PFAD_RE" -- "$f" >/dev/null 2>&1; then
        treffer "'bugbounty' in Pfadform (Domänen-Leak)" "$f" "$(grep -IinE "$BB_PFAD_RE" -- "$f" | head -1)"
    fi
done

# ── Mustergruppe C: echte Karten ohne .sample-Infix in examples/memory/ ──────────
# Nur die oberste Ebene von examples/memory/ (keine inbox/metrics-Hilfsdateien).
# Erlaubte Nicht-Sample-Dateien: Tier-Indizes + auto-generierte Register.
ERLAUBT_REGEX='^(MEMORY|MEMORY_DEEP|MEMORY_INFRA)\.md$|^reference_.*registry\.md$'
for f in "${FILES[@]}"; do
    case "$f" in
        examples/memory/*.md)
            base="$(basename "$f")"
            dir="$(dirname "$f")"
            # nur top-level (examples/memory), keine Unterordner
            [ "$dir" = "examples/memory" ] || continue
            # .sample-Karten sind genau das, was wir wollen → ok
            case "$base" in
                *.sample.md) continue ;;
            esac
            # Ausnahmen (Indizes/Register) erlaubt
            if echo "$base" | grep -qE "$ERLAUBT_REGEX"; then
                continue
            fi
            treffer "Memory-Karte ohne .sample-Infix" "$f" "echte Karte? -> anonymisieren als *.sample.md"
            ;;
    esac
done

if [ "$FAIL" -ne 0 ]; then
    echo
    echo "privacy: FAIL — bitte Treffer oben bereinigen, bevor committed/released wird."
    exit 1
fi

echo "privacy: clean"
exit 0
