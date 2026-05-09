"""
Schritt 2 – Währungsumrechnung (02_fx_conversion.py)

Regeln (HGB / funktionale Währung):
  GuV   → Durchschnittskurs (Jahresergebnis)
  Bilanz → Stichtagskurs
  Eigenkapital-Positionen (Gezeichnetes Kapital, Kapitalrücklage, Gewinnrücklagen)
           → historischer Kurs; da dieser nicht vorliegt, wird er mit dem
             Stichtagskurs angenähert (konservative Vereinfachung).
  Umrechnungsdifferenz = Bilanz_Aktiva_EUR − Bilanz_Passiva_EUR (nach Kursumrechnung)
           → wird dem Währungsausgleichsposten (WAP) im Eigenkapital zugewiesen.

Nur CH (CHF) und PL (PLN) benötigen eine Umrechnung.
DE, AT, NL sind bereits in EUR.
"""

import json
import logging
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
CONFIG_DIR = ROOT / "config"

# Eigenkapital-Positionen, die zum historischen Kurs umgerechnet werden sollten.
# Da historische Kurse nicht vorliegen, werden sie hier ebenfalls zum Stichtagskurs
# umgerechnet – die entstehende Differenz fließt in den WAP.
_EK_POSITIONEN = {
    "Gezeichnetes Kapital",
    "Kapitalrücklage",
    "Gewinnrücklagen",
    "Jahresüberschuss (→GuV)",
    "Summe Eigenkapital",
}


def lade_fx_kurse() -> dict:
    """Liest Wechselkurse aus config/fx_rates.json."""
    pfad = CONFIG_DIR / "fx_rates.json"
    kurse = json.loads(pfad.read_text(encoding="utf-8"))
    log.info(
        "FX-Kurse geladen (Stichtag %s): CHF/EUR=%.4f / %.4f, PLN/EUR=%.4f / %.4f",
        kurse["stichtag"],
        kurse["CHF_EUR"]["stichtag"],
        kurse["CHF_EUR"]["durchschnitt"],
        kurse["PLN_EUR"]["stichtag"],
        kurse["PLN_EUR"]["durchschnitt"],
    )
    return kurse


def _kurs_schluessel(waehrung: str) -> str:
    """Gibt den JSON-Schlüssel für eine Währung zurück (z.B. 'CHF' → 'CHF_EUR')."""
    return f"{waehrung}_EUR"


def konvertiere_guv(guv: pd.DataFrame, waehrung: str, kurse: dict) -> pd.DataFrame:
    """
    Rechnet alle GuV-Positionen mit dem Durchschnittskurs in EUR um.
    Gibt ein neues DataFrame mit identischer Struktur zurück (Werte in TEUR).
    """
    if waehrung == "EUR":
        return guv.copy()

    kurs = kurse[_kurs_schluessel(waehrung)]["durchschnitt"]
    log.info("GuV %s → EUR  Durchschnittskurs %.4f", waehrung, kurs)

    guv_eur = guv.copy()
    guv_eur["2024"] = (guv_eur["2024"] * kurs).round(1)
    guv_eur["2023"] = (guv_eur["2023"] * kurs).round(1)
    return guv_eur


def konvertiere_bilanz(
    bilanz: pd.DataFrame, waehrung: str, kurse: dict
) -> tuple[pd.DataFrame, float]:
    """
    Rechnet alle Bilanzpositionen mit dem Stichtagskurs in EUR um.
    Eigenkapital-Positionen werden ebenfalls zum Stichtagskurs umgerechnet
    (Vereinfachung; Differenz → WAP).

    Rückgabe:
        bilanz_eur  – umgerechnetes DataFrame
        wap         – Währungsausgleichsposten in TEUR (kann negativ sein)
    """
    if waehrung == "EUR":
        return bilanz.copy(), 0.0

    kurs = kurse[_kurs_schluessel(waehrung)]["stichtag"]
    log.info("Bilanz %s → EUR  Stichtagskurs %.4f", waehrung, kurs)

    bilanz_eur = bilanz.copy()
    bilanz_eur["2024"] = (bilanz_eur["2024"] * kurs).round(1)
    bilanz_eur["2023"] = (bilanz_eur["2023"] * kurs).round(1)

    # Währungsausgleichsposten: Differenz Aktiva – Passiva nach Umrechnung
    aktiva_summe = bilanz_eur.loc[
        bilanz_eur["Position"] == "BILANZSUMME AKTIVA", "2024"
    ].sum()
    passiva_summe = bilanz_eur.loc[
        bilanz_eur["Position"] == "BILANZSUMME PASSIVA", "2024"
    ].sum()
    wap = round(aktiva_summe - passiva_summe, 1)

    return bilanz_eur, wap


def konvertiere_gesellschaft(d: dict, kurse: dict) -> dict:
    """
    Konvertiert GuV und Bilanz einer Gesellschaft in EUR.
    Gibt ein neues dict mit denselben Keys zurück, ergänzt um 'wap_teur'.
    """
    waehrung = d["waehrung"]
    guv_eur = konvertiere_guv(d["guv"], waehrung, kurse)
    bilanz_eur, wap = konvertiere_bilanz(d["bilanz"], waehrung, kurse)

    return {
        **d,
        "guv": guv_eur,
        "bilanz": bilanz_eur,
        "waehrung_orig": waehrung,
        "waehrung": "EUR",
        "wap_teur": wap,
    }


def konvertiere_alle(daten: dict, kurse: dict) -> dict:
    """
    Wendet Währungsumrechnung auf alle Gesellschaften an.
    Gibt ein neues dict mit EUR-Werten zurück.
    """
    ergebnis = {}
    for key, d in daten.items():
        if d["waehrung"] == "EUR":
            ergebnis[key] = {**d, "waehrung_orig": "EUR", "wap_teur": 0.0}
            log.info("%s: bereits in EUR – keine Umrechnung.", d["name"])
        else:
            ergebnis[key] = konvertiere_gesellschaft(d, kurse)
            log.info(
                "%s: %s → EUR  WAP=%.1f TEUR",
                d["name"],
                d["waehrung"],
                ergebnis[key]["wap_teur"],
            )
    return ergebnis


def print_fx_uebersicht(daten_eur: dict, kurse: dict | None = None) -> None:
    """Gibt eine Übersicht der Bilanzsummen nach FX-Umrechnung aus."""
    if kurse is None:
        kurse = lade_fx_kurse()

    sep = "─" * 90
    print()
    print(sep)
    print("  BILANZSUMMEN NACH FX-UMRECHNUNG (alle Werte in TEUR)")
    print(sep)
    print(
        f"  {'Gesellschaft':<26} {'Orig.':<6}"
        f" {'FX-Kurs':>8}  {'Aktiva EUR':>12} {'Passiva EUR':>12} {'WAP':>8}"
    )
    print(sep)

    for key, d in daten_eur.items():
        bilanz = d["bilanz"]
        aktiva = bilanz.loc[bilanz["Position"] == "BILANZSUMME AKTIVA", "2024"]
        passiva = bilanz.loc[bilanz["Position"] == "BILANZSUMME PASSIVA", "2024"]
        a = float(aktiva.iloc[0]) if not aktiva.empty else float("nan")
        p = float(passiva.iloc[0]) if not passiva.empty else float("nan")

        waehrung_orig = d.get("waehrung_orig", "EUR")
        if waehrung_orig == "EUR":
            kurs_str = "1.0000"
        else:
            kurs_str = f"{kurse[_kurs_schluessel(waehrung_orig)]['stichtag']:.4f}"

        wap = d.get("wap_teur", 0.0)
        wap_str = f"{wap:+.1f}" if wap != 0.0 else "—"

        print(
            f"  {d['name']:<26} {waehrung_orig:<6}"
            f" {kurs_str:>8}  {a:>12,.1f} {p:>12,.1f} {wap_str:>8}"
        )

    print(sep)
    print()


# ---------------------------------------------------------------------------
# Standalone-Ausführung (python src/02_fx_conversion.py)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "load_data", ROOT / "src" / "01_load_data.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    daten = mod.load_all()
    kurse = lade_fx_kurse()
    daten_eur = konvertiere_alle(daten, kurse)
    print_fx_uebersicht(daten_eur)
