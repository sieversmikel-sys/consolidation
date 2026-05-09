"""
Schritt 4 – Minderheitenanteile (04_minority_interest.py)

Berechnet die Minderheitenanteile (Nicht-beherrschende Anteile) für
Gesellschaften, an denen die Holding weniger als 100% hält:

    Muster CH AG    – 80% Holding / 20% Minderheit
    Muster NL B.V.  – 75% Holding / 25% Minderheit

Ermittelte Größen je Minderheits-Gesellschaft:
    - Minderheit am Eigenkapital (Bilanz-Passiva, Position „Minderheitenanteile")
    - Minderheit am Jahresüberschuss (GuV-Position „Minderheitsergebnis")

Ausweis nach HGB §307:
    Bilanz  → eigene Position unter Eigenkapital: „Minderheitenanteile"
    GuV     → eigene Position nach Jahresüberschuss: „Minderheitsergebnis"

Eingabe:  dict aus 03_ic_elimination.eliminiere_ic()  (Werte in TEUR/EUR)
Ausgabe:  dict mit ergänzten DataFrames + 'minderheit_log'
"""

import logging
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent

_SUMME_EK_POS = "Summe Eigenkapital"
_JUE_GUV_POS = "JAHRESÜBERSCHUSS"          # Positionsname in der GuV
_JUE_BILANZ_POS = "Jahresüberschuss (→GuV)" # Positionsname in der Bilanz
_MINDERHEIT_BILANZ = "Minderheitenanteile"
_MINDERHEIT_GUV = "Minderheitsergebnis"


# ---------------------------------------------------------------------------
# Kern-Berechnung
# ---------------------------------------------------------------------------

def berechne_minderheit(d: dict) -> dict:
    """
    Berechnet Minderheitsanteile für eine Gesellschaft.

    Rückgabe-dict:
        minderheitsquote        float   (z.B. 0.20)
        ek_gesamt_teur          float   Summe Eigenkapital in TEUR (EUR-Basis)
        jue_gesamt_teur         float   Jahresüberschuss in TEUR
        minderheit_ek_teur      float   Minderheit × EK
        minderheit_jue_teur     float   Minderheit × Jahresüberschuss
        holding_ek_teur         float   Holding-Anteil am EK
    """
    quote = d["minderheit"]
    bilanz = d["bilanz"]
    guv = d["guv"]

    # Summe Eigenkapital aus Bilanz-Passiva
    mask_ek = (bilanz["Position"] == _SUMME_EK_POS) & (bilanz["Seite"] == "Passiva")
    ek = float(bilanz.loc[mask_ek, "2024"].sum()) if mask_ek.any() else 0.0

    # Jahresüberschuss aus GuV-Index (Positionsname dort in Großbuchstaben)
    jue = float(guv.loc[_JUE_GUV_POS, "2024"]) if _JUE_GUV_POS in guv.index else 0.0

    return {
        "minderheitsquote": quote,
        "ek_gesamt_teur": ek,
        "jue_gesamt_teur": jue,
        "minderheit_ek_teur": round(ek * quote, 1),
        "minderheit_jue_teur": round(jue * quote, 1),
        "holding_ek_teur": round(ek * (1 - quote), 1),
    }


def _fuge_minderheit_bilanz_ein(bilanz: pd.DataFrame, betrag: float) -> pd.DataFrame:
    """
    Fügt „Minderheitenanteile" direkt nach „Summe Eigenkapital" in die Passiva ein.
    Ist die Position bereits vorhanden, wird sie aktualisiert.
    """
    bilanz = bilanz.copy()

    neue_zeile = pd.DataFrame([{
        "Position": _MINDERHEIT_BILANZ,
        "Seite": "Passiva",
        "2024": betrag,
        "2023": None,
    }])

    # Falls bereits vorhanden – aktualisieren
    maske = (bilanz["Position"] == _MINDERHEIT_BILANZ) & (bilanz["Seite"] == "Passiva")
    if maske.any():
        bilanz.loc[maske, "2024"] = betrag
        return bilanz

    # Hinter „Summe Eigenkapital" einfügen
    idx_ek = bilanz.index[
        (bilanz["Position"] == _SUMME_EK_POS) & (bilanz["Seite"] == "Passiva")
    ]
    if len(idx_ek) > 0:
        pos = idx_ek[-1] + 1
        oben = bilanz.iloc[:pos]
        unten = bilanz.iloc[pos:]
        bilanz = pd.concat([oben, neue_zeile, unten], ignore_index=True)
    else:
        bilanz = pd.concat([bilanz, neue_zeile], ignore_index=True)

    return bilanz


def _fuge_minderheit_guv_ein(guv: pd.DataFrame, betrag: float) -> pd.DataFrame:
    """
    Fügt „Minderheitsergebnis" (negativ – Abzug vom Konzerngewinn) direkt
    nach „JAHRESÜBERSCHUSS" in die GuV ein.
    """
    guv = guv.copy()

    if _MINDERHEIT_GUV in guv.index:
        guv.loc[_MINDERHEIT_GUV, "2024"] = -betrag
        return guv

    neue_zeile = pd.DataFrame(
        [{"2024": -betrag, "2023": None}],
        index=pd.Index([_MINDERHEIT_GUV], name="Position"),
    )

    if _JUE_GUV_POS in guv.index:
        pos = guv.index.get_loc(_JUE_GUV_POS) + 1
        oben = guv.iloc[:pos]
        unten = guv.iloc[pos:]
        guv = pd.concat([oben, neue_zeile, unten])
    else:
        guv = pd.concat([guv, neue_zeile])

    return guv


# ---------------------------------------------------------------------------
# Öffentliche API
# ---------------------------------------------------------------------------

def berechne_alle_minderheiten(daten: dict) -> tuple[dict, dict]:
    """
    Berechnet Minderheitenanteile für alle Gesellschaften mit minderheit > 0,
    schreibt die Ergebnisse in die jeweiligen DataFrames zurück.

    Rückgabe:
        daten_aktualisiert  – dict mit ergänzten GuV/Bilanz-DFs
        minderheit_log      – dict mit Detailergebnissen je Gesellschaft
    """
    daten = {k: dict(d) for k, d in daten.items()}
    minderheit_log: dict = {}

    for key, d in daten.items():
        if d["minderheit"] == 0.0:
            continue

        ergebnis = berechne_minderheit(d)
        minderheit_log[key] = ergebnis

        # Bilanz aktualisieren
        bilanz = _fuge_minderheit_bilanz_ein(d["bilanz"], ergebnis["minderheit_ek_teur"])
        # GuV aktualisieren
        guv = _fuge_minderheit_guv_ein(d["guv"], ergebnis["minderheit_jue_teur"])

        daten[key] = {**d, "bilanz": bilanz, "guv": guv}

        log.info(
            "%s (%.0f%% Minderheit): EK %.1f TEUR → Minderheit %.1f TEUR | "
            "JÜ %.1f TEUR → Minderheitsergebnis %.1f TEUR",
            d["name"],
            ergebnis["minderheitsquote"] * 100,
            ergebnis["ek_gesamt_teur"],
            ergebnis["minderheit_ek_teur"],
            ergebnis["jue_gesamt_teur"],
            ergebnis["minderheit_jue_teur"],
        )

    return daten, minderheit_log


# ---------------------------------------------------------------------------
# Ausgabe
# ---------------------------------------------------------------------------

def print_minderheit_uebersicht(minderheit_log: dict, daten: dict) -> None:
    sep = "─" * 74
    print()
    print(sep)
    print("  MINDERHEITENANTEILE (HGB §307) – alle Werte in TEUR")
    print(sep)
    print(
        f"  {'Gesellschaft':<24} {'Quote':>6}"
        f" {'EK gesamt':>12} {'Minderh. EK':>13}"
        f" {'JÜ gesamt':>11} {'Minderh. JÜ':>13}"
    )
    print(sep)

    for key, e in minderheit_log.items():
        name = daten[key]["name"]
        print(
            f"  {name:<24} {e['minderheitsquote']:>5.0%}"
            f" {e['ek_gesamt_teur']:>12,.1f} {e['minderheit_ek_teur']:>13,.1f}"
            f" {e['jue_gesamt_teur']:>11,.1f} {e['minderheit_jue_teur']:>13,.1f}"
        )

    print(sep)

    # Konzern-Gesamtsicht
    total_min_ek = sum(e["minderheit_ek_teur"] for e in minderheit_log.values())
    total_min_jue = sum(e["minderheit_jue_teur"] for e in minderheit_log.values())
    print(f"  {'SUMME Minderheiten':<24} {'':>6} {'':>12} {total_min_ek:>13,.1f} {'':>11} {total_min_jue:>13,.1f}")
    print(sep)
    print()
    print("  Ausweis in der Konzernbilanz unter Eigenkapital:")
    print(f"    Minderheitenanteile gesamt: {total_min_ek:>10,.1f} TEUR")
    print()
    print("  Ausweis in der Konzern-GuV nach Jahresüberschuss:")
    print(f"    davon Minderheitsergebnis:  {total_min_jue:>10,.1f} TEUR (Abzug)")
    print(f"    Konzernergebnis (Holding):  {sum(e['jue_gesamt_teur'] - e['minderheit_jue_teur'] for e in minderheit_log.values()):>10,.1f} TEUR")
    print(sep)
    print()


# ---------------------------------------------------------------------------
# Standalone-Ausführung
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import importlib.util

    def _lm(name: str, pfad: Path):
        spec = importlib.util.spec_from_file_location(name, pfad)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    src = ROOT / "src"
    m1 = _lm("load_data",    src / "01_load_data.py")
    m2 = _lm("fx",           src / "02_fx_conversion.py")
    m3 = _lm("ic",           src / "03_ic_elimination.py")

    daten_roh = m1.load_all()
    kurse     = m2.lade_fx_kurse()
    daten_eur = m2.konvertiere_alle(daten_roh, kurse)
    daten_ic, _  = m3.eliminiere_ic(daten_eur)

    daten_min, min_log = berechne_alle_minderheiten(daten_ic)
    print_minderheit_uebersicht(min_log, daten_min)
