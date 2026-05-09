"""
Schritt 3 – Intercompany-Eliminierung (03_ic_elimination.py)

Eliminiert drei Kategorien von IC-Positionen:

1. Aufwands-/Ertragskonsolidierung (GuV)
   Alle Positionen, deren Name mit „Intercompany" oder „IC-Materialaufwand"
   beginnt, werden auf 0 gesetzt und im Eliminierungslog erfasst.

2. Schuldenkonsolidierung (Bilanz)
   IC-Forderungen und IC-Verbindlichkeiten werden auf 0 gesetzt.
   Ein offener Saldo wird als „IC-Saldo-Differenz" im Log ausgewiesen.

3. Zwischengewinn (Stub)
   Nicht implementiert (keine Lagerbestands-Bewertung in den Rohdaten);
   Hinweis wird im Log ausgegeben.

Die Beteiligungskonsolidierung (Buchwert vs. EK-Tochter) erfolgt in Schritt 4.

Eingabe:  dict aus 02_fx_conversion.konvertiere_alle()  (Werte in TEUR/EUR)
Ausgabe:  dict mit IC-bereinigten DataFrames + 'ic_log' pro Gesellschaft
"""

import json
import logging
import re
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
CONFIG_DIR = ROOT / "config"

# Muster für IC-GuV-Positionen (Ertragsseite und Aufwandsseite)
_IC_ERTRAG_RE = re.compile(r"^Intercompany\s*\(", re.IGNORECASE)
_IC_AUFWAND_RE = re.compile(r"^IC-Materialaufwand\s*\(", re.IGNORECASE)

# Bilanz-Positionsnamen für IC
_IC_FORDERUNG = "IC-Forderungen"
_IC_VERBINDLICHKEIT = "IC-Verbindlichkeiten"


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def lade_ic_transaktionen() -> list[dict]:
    pfad = CONFIG_DIR / "ic_transactions.json"
    return json.loads(pfad.read_text(encoding="utf-8"))


def _nullstellen_guv(guv: pd.DataFrame, pattern: re.Pattern) -> tuple[pd.DataFrame, float, list[str]]:
    """
    Setzt alle Positionen, die auf `pattern` passen, auf 0.
    Gibt (bereinigtes_df, eliminierter_betrag_2024, liste_der_positionen) zurück.
    """
    guv = guv.copy()
    maske = guv.index.str.contains(pattern, regex=True, na=False)
    positionen = list(guv.index[maske])
    betrag = float(guv.loc[maske, "2024"].sum())
    guv.loc[maske, "2024"] = 0.0
    guv.loc[maske, "2023"] = 0.0
    return guv, betrag, positionen


def _nullstellen_bilanz(
    bilanz: pd.DataFrame, position: str, seite: str
) -> tuple[pd.DataFrame, float]:
    """Setzt eine Bilanzposition auf 0, gibt eliminierten Betrag zurück."""
    bilanz = bilanz.copy()
    maske = (bilanz["Position"] == position) & (bilanz["Seite"] == seite)
    betrag = float(bilanz.loc[maske, "2024"].sum())
    bilanz.loc[maske, "2024"] = 0.0
    bilanz.loc[maske, "2023"] = 0.0
    return bilanz, betrag


# ---------------------------------------------------------------------------
# Kern-Eliminierungen
# ---------------------------------------------------------------------------

def _eliminiere_guv_ic(daten: dict) -> tuple[dict, dict]:
    """
    Aufwands-/Ertragskonsolidierung:
    Nullstellt alle IC-Ertrags- und IC-Aufwandspositionen in jeder GuV.
    Gibt aktualisierte Daten + Zusammenfassung (ertrag, aufwand, saldo) zurück.
    """
    daten = {k: dict(d) for k, d in daten.items()}
    zusammenfassung = {}

    total_ertrag = 0.0
    total_aufwand = 0.0

    for key, d in daten.items():
        guv, ertrag, pos_e = _nullstellen_guv(d["guv"], _IC_ERTRAG_RE)
        guv, aufwand, pos_a = _nullstellen_guv(guv, _IC_AUFWAND_RE)

        daten[key] = {**d, "guv": guv}
        total_ertrag += ertrag
        total_aufwand += aufwand

        zusammenfassung[key] = {
            "ic_ertrag_elim": ertrag,
            "ic_aufwand_elim": aufwand,
            "positionen_ertrag": pos_e,
            "positionen_aufwand": pos_a,
        }
        if pos_e or pos_a:
            log.info(
                "  GuV-Eliminierung %s: Ertrag %.1f / Aufwand %.1f TEUR",
                d["name"], ertrag, aufwand,
            )

    saldo = round(total_ertrag + total_aufwand, 1)
    if abs(saldo) > 0.5:
        log.warning(
            "GuV IC-Saldo ≠ 0: Erträge %.1f / Aufwendungen %.1f / Saldo %.1f TEUR "
            "(Zwischengewinne oder Dateninkonsitenzen – prüfen!)",
            total_ertrag, total_aufwand, saldo,
        )
    else:
        log.info("GuV IC-Saldo = %.1f TEUR – ausgeglichen.", saldo)

    return daten, {"total_ertrag": total_ertrag, "total_aufwand": total_aufwand,
                   "saldo": saldo, "detail": zusammenfassung}


def _eliminiere_bilanz_schulden(daten: dict) -> tuple[dict, dict]:
    """
    Schuldenkonsolidierung:
    Nullstellt IC-Forderungen (Aktiva) und IC-Verbindlichkeiten (Passiva).
    """
    daten = {k: dict(d) for k, d in daten.items()}

    total_forderung = 0.0
    total_verbindlichkeit = 0.0
    detail = {}

    for key, d in daten.items():
        bilanz, ford = _nullstellen_bilanz(d["bilanz"], _IC_FORDERUNG, "Aktiva")
        bilanz, verb = _nullstellen_bilanz(bilanz, _IC_VERBINDLICHKEIT, "Passiva")
        daten[key] = {**d, "bilanz": bilanz}
        total_forderung += ford
        total_verbindlichkeit += verb
        detail[key] = {"ic_forderung_elim": ford, "ic_verbindlichkeit_elim": verb}
        if ford or verb:
            log.info(
                "  Bilanz-Eliminierung %s: Forderung %.1f / Verbindlichkeit %.1f TEUR",
                d["name"], ford, verb,
            )

    saldo = round(total_forderung - total_verbindlichkeit, 1)
    if abs(saldo) > 0.5:
        log.warning(
            "Bilanz IC-Saldo ≠ 0: Forderungen %.1f / Verbindlichkeiten %.1f / Saldo %.1f TEUR",
            total_forderung, total_verbindlichkeit, saldo,
        )
    else:
        log.info("Bilanz IC-Saldo = %.1f TEUR – ausgeglichen.", saldo)

    return daten, {
        "total_forderung": total_forderung,
        "total_verbindlichkeit": total_verbindlichkeit,
        "saldo": saldo,
        "detail": detail,
    }


def _hinweis_zwischengewinn() -> None:
    log.info(
        "Zwischengewinn-Eliminierung: nicht implementiert – "
        "Lagerbestandsbewertung der Tochtergesellschaften liegt nicht vor."
    )


# ---------------------------------------------------------------------------
# Öffentliche API
# ---------------------------------------------------------------------------

def eliminiere_ic(daten: dict) -> tuple[dict, dict]:
    """
    Führt alle IC-Eliminierungsschritte durch.

    Eingabe:  daten  – Ergebnis von 02_fx_conversion.konvertiere_alle()
    Ausgabe:  (daten_bereinigt, ic_log)
        ic_log = {
            "guv":    {total_ertrag, total_aufwand, saldo, detail},
            "bilanz": {total_forderung, total_verbindlichkeit, saldo, detail},
        }
    """
    log.info("─── IC-Eliminierung: GuV (Aufwands-/Ertragskonsolidierung) ───")
    daten, guv_log = _eliminiere_guv_ic(daten)

    log.info("─── IC-Eliminierung: Bilanz (Schuldenkonsolidierung) ───")
    daten, bilanz_log = _eliminiere_bilanz_schulden(daten)

    _hinweis_zwischengewinn()

    return daten, {"guv": guv_log, "bilanz": bilanz_log}


# ---------------------------------------------------------------------------
# Ausgabe
# ---------------------------------------------------------------------------

def print_ic_uebersicht(ic_log: dict) -> None:
    sep = "─" * 72

    g = ic_log["guv"]
    b = ic_log["bilanz"]

    print()
    print(sep)
    print("  IC-ELIMINIERUNG – ZUSAMMENFASSUNG (Werte in TEUR)")
    print(sep)

    print()
    print("  GuV – Aufwands-/Ertragskonsolidierung")
    print(f"  {'Gesellschaft':<26} {'IC-Ertrag':>12} {'IC-Aufwand':>12}")
    print("  " + "·" * 52)
    for key, d in g["detail"].items():
        if d["ic_ertrag_elim"] or d["ic_aufwand_elim"]:
            print(
                f"  {key:<26}"
                f" {d['ic_ertrag_elim']:>12,.1f}"
                f" {d['ic_aufwand_elim']:>12,.1f}"
            )
    print("  " + "·" * 52)
    saldo_ok = "✅" if abs(g["saldo"]) <= 0.5 else "⚠️ "
    print(
        f"  {'SUMME':<26} {g['total_ertrag']:>12,.1f} {g['total_aufwand']:>12,.1f}"
        f"   Saldo {g['saldo']:+.1f}  {saldo_ok}"
    )

    print()
    print("  Bilanz – Schuldenkonsolidierung")
    print(f"  {'Gesellschaft':<26} {'IC-Forderung':>14} {'IC-Verbindl.':>14}")
    print("  " + "·" * 56)
    for key, d in b["detail"].items():
        if d["ic_forderung_elim"] or d["ic_verbindlichkeit_elim"]:
            print(
                f"  {key:<26}"
                f" {d['ic_forderung_elim']:>14,.1f}"
                f" {d['ic_verbindlichkeit_elim']:>14,.1f}"
            )
    print("  " + "·" * 56)
    saldo_ok = "✅" if abs(b["saldo"]) <= 0.5 else "⚠️ "
    print(
        f"  {'SUMME':<26} {b['total_forderung']:>14,.1f}"
        f" {b['total_verbindlichkeit']:>14,.1f}"
        f"   Saldo {b['saldo']:+.1f}  {saldo_ok}"
    )

    print()
    print(sep)
    print()


# ---------------------------------------------------------------------------
# Standalone-Ausführung
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import importlib.util

    def _lade_modul(name: str, pfad: Path):
        spec = importlib.util.spec_from_file_location(name, pfad)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    src = ROOT / "src"
    m1 = _lade_modul("load_data", src / "01_load_data.py")
    m2 = _lade_modul("fx_conversion", src / "02_fx_conversion.py")

    daten_roh = m1.load_all()
    kurse = m2.lade_fx_kurse()
    daten_eur = m2.konvertiere_alle(daten_roh, kurse)

    daten_ic, ic_log = eliminiere_ic(daten_eur)
    print_ic_uebersicht(ic_log)
