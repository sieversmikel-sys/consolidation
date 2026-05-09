"""
Konzernkonsolidierung – Streamlit-App
Startet mit: streamlit run app.py
"""

import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "src"))

COMMENTS_FILE = ROOT / "config" / "comments.json"

_COMMENT_KEYS = [
    "guv_gesamt",
    "umsatz",
    "ebit",
    "konzernergebnis",
    "bilanz_gesamt",
    "eigenkapital",
    "verbindlichkeiten",
    "segment",
    "ic",
    "sonstige",
]


def _lade_kommentare() -> dict:
    if COMMENTS_FILE.exists():
        return json.loads(COMMENTS_FILE.read_text(encoding="utf-8"))
    return {k: "" for k in _COMMENT_KEYS}


def _speichere_kommentare(kommentare: dict) -> None:
    COMMENTS_FILE.write_text(
        json.dumps(kommentare, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Pipeline laden – Module einmalig beim App-Start laden (kein cache_resource)
# ---------------------------------------------------------------------------

import types, sys

def _lm(name: str, pfad: Path):
    """Lädt ein Python-Modul per exec() – kompatibel mit read-only Filesystemen."""
    mod = types.ModuleType(name)
    mod.__file__ = str(pfad)
    mod.__name__ = name
    code = compile(pfad.read_text(encoding="utf-8"), str(pfad), "exec")
    exec(code, mod.__dict__)
    sys.modules[name] = mod
    return mod


_src = ROOT / "src" if (ROOT / "src" / "01_load_data.py").exists() else ROOT
_m1 = _lm("load_data", _src / "01_load_data.py")
_m2 = _lm("fx",        _src / "02_fx_conversion.py")
_m3 = _lm("ic",        _src / "03_ic_elimination.py")
_m4 = _lm("mi",        _src / "04_minority_interest.py")
_m5 = _lm("co",        _src / "05_consolidate.py")
_m6 = _lm("ex",        _src / "06_export_excel.py")


@st.cache_data(show_spinner="Pipeline wird berechnet …")
def _run_pipeline(chf_stichtag: float, chf_durch: float,
                  pln_stichtag: float, pln_durch: float):
    """Führt die komplette Pipeline durch. Cache-Key = FX-Kurse."""
    kurse = {
        "stichtag": "2024-12-31",
        "CHF_EUR": {"stichtag": chf_stichtag, "durchschnitt": chf_durch},
        "PLN_EUR": {"stichtag": pln_stichtag, "durchschnitt": pln_durch},
    }

    import logging
    logging.disable(logging.CRITICAL)

    daten          = _m1.load_all()
    daten          = _m2.konvertiere_alle(daten, kurse)
    daten, ic_log  = _m3.eliminiere_ic(daten)
    daten, min_log = _m4.berechne_alle_minderheiten(daten)
    guv, bilanz    = _m5.konsolidiere(daten)

    logging.disable(logging.NOTSET)
    return guv, bilanz, daten, ic_log, min_log


# ---------------------------------------------------------------------------
# Hilfsfunktionen Darstellung
# ---------------------------------------------------------------------------

_SUBTOTALS_GUV = {
    "Gesamtumsatz", "Summe sonstige Erträge", "GESAMTLEISTUNG",
    "Summe Aufwendungen", "EBIT", "Summe Finanzergebnis",
    "EBT (Ergebnis vor Steuern)", "JAHRESÜBERSCHUSS", "Konzernergebnis",
}
_SUBTOTALS_BILANZ = {
    "Summe Anlagevermögen", "Summe Umlaufvermögen", "BILANZSUMME AKTIVA",
    "Summe Eigenkapital", "Summe Rückstellungen", "Summe Verbindlichkeiten",
    "BILANZSUMME PASSIVA",
}


def _fmt(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{v:,.1f}"


def _delta_pct(v24, v23) -> str:
    if not v23 or abs(v23) < 0.1:
        return "—"
    return f"{(v24 - v23) / abs(v23):+.1%}"


def _style_guv(df: pd.DataFrame):
    def _row_style(row):
        is_sub = row.name in _SUBTOTALS_GUV
        bg = "background-color: #f0f4f8; font-weight: bold" if is_sub else ""
        return [bg] * len(row)
    return df.style.apply(_row_style, axis=1).format("{:,.1f}", na_rep="—")


def _style_bilanz(df: pd.DataFrame):
    def _row_style(row):
        is_sub = row["Position"] in _SUBTOTALS_BILANZ
        bg = "background-color: #f0f4f8; font-weight: bold" if is_sub else ""
        warn = row["Position"] in ("Währungsausgleichsposten", "Konsolidierungsdifferenz")
        if warn:
            bg = "background-color: #fff0f0; color: #cc0000; font-weight: bold"
        return [bg] * len(row)
    return df.style.apply(_row_style, axis=1)


# ---------------------------------------------------------------------------
# Seiten-Layout
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Konzernkonsolidierung 2024",
    page_icon="🏦",
    layout="wide",
)

st.title("🏦 Konzernkonsolidierung 2024")
st.caption("Muster Holding AG · 5 Tochtergesellschaften · HGB · Angaben in TEUR")

# ---------------------------------------------------------------------------
# Sidebar – FX-Kurse
# ---------------------------------------------------------------------------

with st.sidebar:
    st.header("⚙️ Wechselkurse")
    st.caption("Änderungen → Pipeline wird automatisch neu berechnet")

    _fx_path = ROOT / "config" / "fx_rates.json"
    _fx_defaults = {
        "stichtag": "2024-12-31",
        "CHF_EUR": {"stichtag": 1.058, "durchschnitt": 1.042},
        "PLN_EUR": {"stichtag": 0.233, "durchschnitt": 0.228},
    }
    if _fx_path.exists():
        _raw = json.loads(_fx_path.read_text())
        if "CHF_EUR" in _raw:
            fx_raw = _raw
        else:
            kurse = _raw.get("kurse", {})
            fx_raw = {
                "stichtag": _raw.get("stichtag", "2024-12-31"),
                "CHF_EUR": {
                    "stichtag":    kurse.get("CHF", {}).get("stichtagskurs",    1.058),
                    "durchschnitt": kurse.get("CHF", {}).get("durchschnittskurs", 1.042),
                },
                "PLN_EUR": {
                    "stichtag":    kurse.get("PLN", {}).get("stichtagskurs",    0.233),
                    "durchschnitt": kurse.get("PLN", {}).get("durchschnittskurs", 0.228),
                },
            }
    else:
        fx_raw = _fx_defaults

    st.subheader("CHF → EUR")
    chf_s = st.number_input("Stichtagskurs (Bilanz)",  value=fx_raw["CHF_EUR"]["stichtag"],
                             min_value=0.8, max_value=1.5, step=0.001, format="%.3f", key="chf_s")
    chf_d = st.number_input("Durchschnittskurs (GuV)", value=fx_raw["CHF_EUR"]["durchschnitt"],
                             min_value=0.8, max_value=1.5, step=0.001, format="%.3f", key="chf_d")

    st.subheader("PLN → EUR")
    pln_s = st.number_input("Stichtagskurs (Bilanz)",  value=fx_raw["PLN_EUR"]["stichtag"],
                             min_value=0.1, max_value=0.5, step=0.001, format="%.3f", key="pln_s")
    pln_d = st.number_input("Durchschnittskurs (GuV)", value=fx_raw["PLN_EUR"]["durchschnitt"],
                             min_value=0.1, max_value=0.5, step=0.001, format="%.3f", key="pln_d")

    if st.button("💾 Kurse in fx_rates.json speichern"):
        fx_raw["CHF_EUR"] = {"stichtag": chf_s, "durchschnitt": chf_d}
        fx_raw["PLN_EUR"] = {"stichtag": pln_s, "durchschnitt": pln_d}
        (ROOT / "config" / "fx_rates.json").write_text(
            json.dumps(fx_raw, indent=2, ensure_ascii=False)
        )
        st.success("Gespeichert ✅")

    st.divider()
    st.caption("Stichtagskurs: 31.12.2024\nQuelle: fx_rates.json")

    # Excel-Download direkt aus dem Speicher (kein Schreiben auf Disk nötig)
    st.markdown("---")
    st.markdown("**⬇️ Excel-Export**")
    if st.button("Konzernabschluss generieren"):
        import io
        buf = io.BytesIO()
        # temporäre Datei im Speicher
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
            tmp_path = pathlib.Path(tmp.name)
        _m6.exportiere_excel(guv, bilanz, daten, ic_log, pfad=tmp_path)
        buf.write(tmp_path.read_bytes())
        os.unlink(tmp_path)
        buf.seek(0)
        st.download_button(
            "📥 Download Konzernabschluss_2024.xlsx",
            data=buf,
            file_name="Konzernabschluss_2024.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

# ---------------------------------------------------------------------------
# Pipeline ausführen
# ---------------------------------------------------------------------------

guv, bilanz, daten, ic_log, min_log = _run_pipeline(chf_s, chf_d, pln_s, pln_d)

# ---------------------------------------------------------------------------
# KPI-Zeile
# ---------------------------------------------------------------------------

def _g(pos):
    return float(guv.loc[pos, "2024"]) if pos in guv.index else 0.0

def _g23(pos):
    return float(guv.loc[pos, "2023"]) if pos in guv.index else 0.0

def _b(pos, seite="Aktiva"):
    row = bilanz[(bilanz["Position"] == pos) & (bilanz["Seite"] == seite)]
    return float(row["2024"].iloc[0]) if not row.empty else 0.0

umsatz    = _g("Gesamtumsatz")
umsatz_vj = _g23("Gesamtumsatz")
ebit      = _g("EBIT")
ebit_vj   = _g23("EBIT")
ke        = _g("Konzernergebnis")
ke_vj     = _g23("Konzernergebnis")
bs        = _b("BILANZSUMME AKTIVA")

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Konzernumsatz",    f"{umsatz:,.0f} TEUR",  f"{(umsatz-umsatz_vj)/abs(umsatz_vj):+.1%} vs. VJ")
col2.metric("EBIT",             f"{ebit:,.0f} TEUR",    f"{(ebit-ebit_vj)/abs(ebit_vj):+.1%} vs. VJ")
col3.metric("EBIT-Marge",       f"{ebit/umsatz:.1%}",   f"{ebit/umsatz - ebit_vj/umsatz_vj:+.1%} vs. VJ")
col4.metric("Konzernergebnis",  f"{ke:,.0f} TEUR",      f"{(ke-ke_vj)/abs(ke_vj):+.1%} vs. VJ" if ke_vj else "")
col5.metric("Bilanzsumme",      f"{bs:,.0f} TEUR")

st.divider()

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

kommentare = _lade_kommentare()

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "📊 Konzern-GuV",
    "🏛 Konzern-Bilanz",
    "💧 Kapitalflussrechnung",
    "🗺 Segmentbericht",
    "🔗 IC-Eliminierungen",
    "📝 Analyse & Kommentare",
])

# ── Tab 1: GuV ──────────────────────────────────────────────────────────────
with tab1:
    st.subheader("Konzern-Gewinn- und Verlustrechnung 2024")

    col_a, col_b = st.columns([3, 2])

    with col_a:
        guv_display = guv[["2024", "2023"]].copy()
        guv_display.columns = ["2024 (TEUR)", "2023 (TEUR)"]
        guv_display["Δ %"] = guv_display.apply(
            lambda r: f"{(r['2024 (TEUR)']-r['2023 (TEUR)'])/abs(r['2023 (TEUR)']):+.1%}"
            if r["2023 (TEUR)"] and abs(r["2023 (TEUR)"]) > 0.1 else "—", axis=1
        )
        st.dataframe(
            guv_display.style.apply(
                lambda row: [
                    "background-color:#f0f4f8;font-weight:bold" if row.name in _SUBTOTALS_GUV else ""
                ] * len(row), axis=1
            ).format({"2024 (TEUR)": "{:,.1f}", "2023 (TEUR)": "{:,.1f}"}),
            use_container_width=True, height=600,
        )

    with col_b:
        st.caption("EBIT-Entwicklung")
        ebit_chart = pd.DataFrame({
            "2023": [_g23("EBIT")],
            "2024": [_g("EBIT")],
        }, index=["EBIT"])
        st.bar_chart(ebit_chart.T, use_container_width=True)

        st.caption("Aufwandsstruktur 2024 (TEUR)")
        aufwand = pd.Series({
            "Material":    abs(_g("Materialaufwand")),
            "Personal":    abs(_g("Personalaufwand")),
            "AfA":         abs(_g("Abschreibungen (AfA)")),
            "Sonstiges":   abs(_g("Sonstiger betrieblicher Aufwand")),
        })
        st.bar_chart(aufwand, use_container_width=True)

# ── Tab 2: Bilanz ────────────────────────────────────────────────────────────
with tab2:
    st.subheader("Konzern-Bilanz 31.12.2024")

    col_a, col_b = st.columns(2)

    aktiva  = bilanz[bilanz["Seite"] == "Aktiva"][["Position", "2024", "2023"]].reset_index(drop=True)
    passiva = bilanz[bilanz["Seite"] == "Passiva"][["Position", "2024", "2023"]].reset_index(drop=True)

    def _style_half(df):
        def row_style(row):
            pos = row["Position"]
            if pos in _SUBTOTALS_BILANZ:
                return ["background-color:#f0f4f8;font-weight:bold"] * len(row)
            if pos in ("Währungsausgleichsposten", "Konsolidierungsdifferenz"):
                return ["background-color:#fff0f0;color:#cc0000;font-weight:bold"] * len(row)
            return [""] * len(row)
        return df.style.apply(row_style, axis=1).format(
            {"2024": "{:,.1f}", "2023": "{:,.1f}"}, na_rep="—"
        )

    with col_a:
        st.caption("AKTIVA")
        st.dataframe(_style_half(aktiva), use_container_width=True, hide_index=True)

    with col_b:
        st.caption("PASSIVA")
        st.dataframe(_style_half(passiva), use_container_width=True, hide_index=True)

    # Passiva-Torte
    st.caption("Passiva-Struktur 2024")
    ek  = _b("Summe Eigenkapital", "Passiva")
    rk  = _b("Summe Rückstellungen", "Passiva")
    vb  = _b("Summe Verbindlichkeiten", "Passiva")
    st.bar_chart(pd.DataFrame({
        "Eigenkapital": [ek], "Rückstellungen": [rk], "Verbindlichkeiten": [vb]
    }), use_container_width=True, height=160)

# ── Tab 3: KFR ───────────────────────────────────────────────────────────────
with tab3:
    st.subheader("Kapitalflussrechnung 2024 (indirekte Methode)")

    def _bd(pos):
        row = bilanz[bilanz["Position"] == pos]
        if row.empty:
            return 0.0
        v24 = row["2024"].iloc[0]
        v23 = row["2023"].iloc[0]
        return float(v24 - v23) if pd.notna(v24) and pd.notna(v23) else 0.0

    jue    = _g("JAHRESÜBERSCHUSS")
    afa    = -_g("Abschreibungen (AfA)")
    d_vorr = _bd("Vorräte")
    d_ford = _bd("Forderungen L&L")
    d_verb = _bd("Verbindlichkeiten L&L")
    cfo    = jue + afa - d_vorr - d_ford + d_verb
    cfi    = -afa * 1.1
    cff    = _bd("Bankverbindlichkeiten") + _bd("Minderheitenanteile")
    netto  = cfo + cfi + cff

    kfr_data = {
        "Position": [
            "I. Cashflow aus Betriebstätigkeit", "  Jahresüberschuss",
            "  + Abschreibungen", "  − Δ Vorräte", "  − Δ Forderungen L&L",
            "  + Δ Verbindlichkeiten L&L", "  = CFO",
            "II. Cashflow aus Investitionen", "  − Investitionen (Näherung)",
            "  = CFI",
            "III. Cashflow aus Finanzierung", "  ± Δ Bankverbindlichkeiten",
            "  = CFF",
            "Netto-Veränderung liquide Mittel",
        ],
        "2024 (TEUR)": [
            None, jue, afa, -d_vorr, -d_ford, d_verb, cfo,
            None, cfi, cfi,
            None, _bd("Bankverbindlichkeiten"), cff,
            netto,
        ],
    }
    kfr_df = pd.DataFrame(kfr_data)

    TOTALS_KFR = {"  = CFO", "  = CFI", "  = CFF", "Netto-Veränderung liquide Mittel"}

    st.dataframe(
        kfr_df.style.apply(
            lambda row: [
                "background-color:#f0f4f8;font-weight:bold"
                if row["Position"] in TOTALS_KFR else ""
            ] * len(row), axis=1
        ).format({"2024 (TEUR)": "{:,.1f}"}, na_rep=""),
        use_container_width=True, hide_index=True, height=480,
    )

    col_c1, col_c2, col_c3 = st.columns(3)
    col_c1.metric("CFO", f"{cfo:,.0f} TEUR")
    col_c2.metric("CFI", f"{cfi:,.0f} TEUR")
    col_c3.metric("CFF", f"{cff:,.0f} TEUR")

# ── Tab 4: Segment ───────────────────────────────────────────────────────────
with tab4:
    st.subheader("Segmentbericht 2024")

    seg_rows = []
    for key, d in daten.items():
        g = d["guv"]
        b = d["bilanz"]

        def _gv(pos):
            return float(g.loc[pos, "2024"]) if pos in g.index else 0.0

        def _bv(pos, seite="Aktiva"):
            row = b[(b["Position"] == pos) & (b["Seite"] == seite)]
            return float(row["2024"].iloc[0]) if not row.empty else 0.0

        umsatz_seg = _gv("Gesamtumsatz")
        ebit_seg   = _gv("EBIT")
        seg_rows.append({
            "Gesellschaft":    d["name"],
            "Land":            d.get("land", ""),
            "Währung":         d.get("waehrung_orig", "EUR"),
            "Beteiligung":     f"{d.get('beteiligung', 1.0):.0%}",
            "Umsatz (TEUR)":   umsatz_seg,
            "EBIT (TEUR)":     ebit_seg,
            "EBIT-Marge":      ebit_seg / umsatz_seg if umsatz_seg else 0,
            "JÜ (TEUR)":       _gv("JAHRESÜBERSCHUSS"),
            "Bilanzsumme":     _bv("BILANZSUMME AKTIVA"),
            "Eigenkapital":    _bv("Summe Eigenkapital", "Passiva"),
        })

    seg_df = pd.DataFrame(seg_rows)

    st.dataframe(
        seg_df.style.format({
            "Umsatz (TEUR)": "{:,.1f}",
            "EBIT (TEUR)":   "{:,.1f}",
            "EBIT-Marge":    "{:.1%}",
            "JÜ (TEUR)":     "{:,.1f}",
            "Bilanzsumme":   "{:,.1f}",
            "Eigenkapital":  "{:,.1f}",
        }),
        use_container_width=True, hide_index=True,
    )

    col_d1, col_d2 = st.columns(2)
    with col_d1:
        st.caption("Umsatz je Gesellschaft (TEUR)")
        st.bar_chart(seg_df.set_index("Gesellschaft")["Umsatz (TEUR)"])
    with col_d2:
        st.caption("EBIT-Marge je Gesellschaft")
        st.bar_chart(seg_df.set_index("Gesellschaft")["EBIT-Marge"])

# ── Tab 5: IC ────────────────────────────────────────────────────────────────
with tab5:
    st.subheader("IC-Eliminierungen – Nachweis")

    g_log = ic_log["guv"]
    b_log = ic_log["bilanz"]

    st.markdown("**I. Aufwands-/Ertragskonsolidierung (GuV)**")
    guv_ic_rows = [
        {"Gesellschaft": k,
         "IC-Ertrag (TEUR)": d["ic_ertrag_elim"],
         "IC-Aufwand (TEUR)": d["ic_aufwand_elim"],
         "Netto (TEUR)": round(d["ic_ertrag_elim"] + d["ic_aufwand_elim"], 1)}
        for k, d in g_log["detail"].items()
        if d["ic_ertrag_elim"] or d["ic_aufwand_elim"]
    ]
    guv_ic_rows.append({
        "Gesellschaft": "SUMME",
        "IC-Ertrag (TEUR)": g_log["total_ertrag"],
        "IC-Aufwand (TEUR)": g_log["total_aufwand"],
        "Netto (TEUR)": round(g_log["saldo"], 1),
    })
    st.dataframe(pd.DataFrame(guv_ic_rows), use_container_width=True, hide_index=True)

    if abs(g_log["saldo"]) > 0.5:
        st.warning(f"⚠️ GuV IC-Saldo {g_log['saldo']:+.1f} TEUR – enthält Zwischengewinne (nicht eliminiert)")
    else:
        st.success("✅ GuV IC ausgeglichen")

    st.markdown("**II. Schuldenkonsolidierung (Bilanz)**")
    bilanz_ic_rows = [
        {"Gesellschaft": k,
         "IC-Forderungen (TEUR)": d["ic_forderung_elim"],
         "IC-Verbindl. (TEUR)": d["ic_verbindlichkeit_elim"],
         "Saldo (TEUR)": round(d["ic_forderung_elim"] - d["ic_verbindlichkeit_elim"], 1)}
        for k, d in b_log["detail"].items()
        if d["ic_forderung_elim"] or d["ic_verbindlichkeit_elim"]
    ]
    bilanz_ic_rows.append({
        "Gesellschaft": "SUMME",
        "IC-Forderungen (TEUR)": b_log["total_forderung"],
        "IC-Verbindl. (TEUR)": b_log["total_verbindlichkeit"],
        "Saldo (TEUR)": round(b_log["saldo"], 1),
    })
    st.dataframe(pd.DataFrame(bilanz_ic_rows), use_container_width=True, hide_index=True)

    if abs(b_log["saldo"]) > 0.5:
        st.warning(f"⚠️ Bilanz IC-Saldo {b_log['saldo']:+.1f} TEUR")
    else:
        st.success("✅ Bilanz IC ausgeglichen")

    # Minderheitenanteile
    st.markdown("**III. Minderheitenanteile (HGB §307)**")
    min_rows = [
        {"Gesellschaft": daten[k]["name"],
         "Quote": f"{e['minderheitsquote']:.0%}",
         "EK gesamt (TEUR)": e["ek_gesamt_teur"],
         "Minderheit EK (TEUR)": e["minderheit_ek_teur"],
         "JÜ gesamt (TEUR)": e["jue_gesamt_teur"],
         "Minderheitsergebnis (TEUR)": e["minderheit_jue_teur"]}
        for k, e in min_log.items()
    ]
    st.dataframe(pd.DataFrame(min_rows), use_container_width=True, hide_index=True)

# ── Tab 6: Analyse & Kommentare ─────────────────────────────────────────────
with tab6:
    st.subheader("Analyse signifikanter Abweichungen & Kommentare")

    # ── Auto-Analyse ─────────────────────────────────────────────────────────
    st.markdown("### Automatische Abweichungsanalyse")
    st.caption("Positionen mit |Δ| > 15 % oder |ΔTEUR| > 500 TEUR gegenüber Vorjahr")

    SCHWELLE_PCT  = 0.15
    SCHWELLE_TEUR = 500.0

    auffaellig = []
    for pos, row in guv.iterrows():
        v24, v23 = row["2024"], row["2023"]
        if not v23 or abs(v23) < 0.1:
            continue
        delta_abs = v24 - v23
        delta_pct = delta_abs / abs(v23)
        if abs(delta_pct) >= SCHWELLE_PCT and abs(delta_abs) >= SCHWELLE_TEUR:
            richtung = "gestiegen" if delta_abs > 0 else "gesunken"
            vorzeichen = "+" if delta_abs > 0 else ""
            auffaellig.append({
                "Bereich": "GuV",
                "Position": pos,
                "2024 (TEUR)": v24,
                "2023 (TEUR)": v23,
                "Δ TEUR": round(delta_abs, 1),
                "Δ %": delta_pct,
                "_text": (
                    f"**{pos}** ist um {vorzeichen}{delta_abs:,.0f} TEUR "
                    f"({vorzeichen}{delta_pct:.1%}) {richtung} "
                    f"(von {v23:,.0f} auf {v24:,.0f} TEUR)."
                ),
            })

    for _, row in bilanz.iterrows():
        pos, v24, v23 = row["Position"], row["2024"], row["2023"]
        if not v23 or abs(v23) < 0.1 or pd.isna(v23) or pd.isna(v24):
            continue
        delta_abs = v24 - v23
        delta_pct = delta_abs / abs(v23)
        if abs(delta_pct) >= SCHWELLE_PCT and abs(delta_abs) >= SCHWELLE_TEUR:
            richtung = "gestiegen" if delta_abs > 0 else "gesunken"
            vorzeichen = "+" if delta_abs > 0 else ""
            auffaellig.append({
                "Bereich": f"Bilanz ({row['Seite']})",
                "Position": pos,
                "2024 (TEUR)": v24,
                "2023 (TEUR)": v23,
                "Δ TEUR": round(delta_abs, 1),
                "Δ %": delta_pct,
                "_text": (
                    f"**{pos}** ({row['Seite']}) ist um {vorzeichen}{delta_abs:,.0f} TEUR "
                    f"({vorzeichen}{delta_pct:.1%}) {richtung}."
                ),
            })

    if auffaellig:
        # Tabelle
        df_auf = pd.DataFrame(auffaellig).drop(columns=["_text"])
        st.dataframe(
            df_auf.style.format({
                "2024 (TEUR)": "{:,.1f}",
                "2023 (TEUR)": "{:,.1f}",
                "Δ TEUR":      "{:+,.1f}",
                "Δ %":         "{:+.1%}",
            }).apply(
                lambda row: [
                    "background-color:#fff0f0" if row["Δ TEUR"] < 0
                    else "background-color:#f0fff0"
                ] * len(row), axis=1
            ),
            use_container_width=True, hide_index=True,
        )

        # Narrative Beschreibung
        st.markdown("#### Narrativ")
        # Top-3 nach absolutem Δ
        top = sorted(auffaellig, key=lambda x: abs(x["Δ TEUR"]), reverse=True)[:5]
        narrative = "Die wesentlichen Veränderungen gegenüber dem Vorjahr:\n\n"
        for item in top:
            narrative += f"- {item['_text']}\n"

        # Besondere Hinweise
        ebit_delta = _g("EBIT") - _g23("EBIT")
        if abs(ebit_delta) > 500:
            narrative += (
                f"\nDas **EBIT** hat sich um {ebit_delta:+,.0f} TEUR verändert "
                f"(Marge: {_g('EBIT')/_g('Gesamtumsatz'):.1%} vs. VJ "
                f"{_g23('EBIT')/_g23('Gesamtumsatz'):.1%})."
            )

        st.markdown(narrative)
    else:
        st.info("Keine signifikanten Abweichungen über den Schwellenwerten gefunden.")

    col_s1, col_s2 = st.columns(2)
    with col_s1:
        neue_schwelle_pct = st.slider(
            "Schwelle Δ % (ab wann auffällig)", 5, 50, 15, step=5,
            format="%d%%", key="schwelle_pct"
        )
    with col_s2:
        neue_schwelle_teur = st.slider(
            "Schwelle Δ TEUR (Mindestbetrag)", 100, 5000, 500, step=100,
            format="%d TEUR", key="schwelle_teur"
        )
    if neue_schwelle_pct != 15 or neue_schwelle_teur != 500:
        st.caption("↑ Schwellen anpassen → Seite wird automatisch neu gerendert.")

    st.divider()

    # ── Kommentare ────────────────────────────────────────────────────────────
    st.markdown("### Kommentare zum Konzernabschluss")
    st.caption("Kommentare werden in config/comments.json gespeichert.")

    felder = {
        "guv_gesamt":       ("📊 Gesamtbeurteilung GuV", "Allgemeine Einschätzung der GuV-Entwicklung …"),
        "umsatz":           ("📈 Umsatzentwicklung", "Kommentar zur Umsatzentwicklung und -treibern …"),
        "ebit":             ("⚙️ EBIT / operatives Ergebnis", "Erläuterung der EBIT-Entwicklung …"),
        "konzernergebnis":  ("💰 Konzernergebnis", "Kommentar zum Konzernjahresüberschuss …"),
        "bilanz_gesamt":    ("🏛 Gesamtbeurteilung Bilanz", "Allgemeine Einschätzung der Bilanzstruktur …"),
        "eigenkapital":     ("🏦 Eigenkapital & Minderheiten", "Kommentar zu EK-Veränderungen und Minderheitenanteilen …"),
        "verbindlichkeiten":("📋 Verbindlichkeiten & Rückstellungen", "Kommentar zur Fremdkapitalstruktur …"),
        "segment":          ("🗺 Segmententwicklung", "Kommentar zu regionalen / gesellschaftsbezogenen Besonderheiten …"),
        "ic":               ("🔗 Intercompany", "Erläuterung der IC-Beziehungen und offener Salden …"),
        "sonstige":         ("📌 Sonstige Hinweise", "Weitere Anmerkungen, Ausblick, Risiken …"),
    }

    geaendert = False
    neue_kommentare = dict(kommentare)

    for key, (label, placeholder) in felder.items():
        with st.expander(label, expanded=bool(kommentare.get(key))):
            wert = st.text_area(
                label, value=kommentare.get(key, ""),
                placeholder=placeholder,
                height=120, label_visibility="collapsed", key=f"komm_{key}"
            )
            if wert != kommentare.get(key, ""):
                neue_kommentare[key] = wert
                geaendert = True

    col_btn1, col_btn2 = st.columns([1, 4])
    with col_btn1:
        if st.button("💾 Speichern", type="primary"):
            _speichere_kommentare(neue_kommentare)
            st.success("Kommentare gespeichert ✅")
            st.rerun()
    with col_btn2:
        if geaendert:
            st.caption("⚠️ Ungespeicherte Änderungen – bitte speichern.")

    # Kommentar-Vorschau (Druckansicht)
    if any(v for v in neue_kommentare.values()):
        st.divider()
        st.markdown("#### Vorschau (Druckansicht)")
        for key, (label, _) in felder.items():
            txt = neue_kommentare.get(key, "")
            if txt:
                st.markdown(f"**{label}**")
                st.markdown(f"> {txt}")

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
st.divider()
st.caption("Konzernkonsolidierung v1.0 · HGB-konform · Angaben in TEUR · Stichtag 31.12.2024")
