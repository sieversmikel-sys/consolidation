"""
Konzernkonsolidierung – Streamlit-App
Startet mit: streamlit run app.py
"""

import json
import sys
import types
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "src"))

COMMENTS_FILE = ROOT / "config" / "comments.json"

_COMMENT_KEYS = [
    "guv_gesamt", "umsatz", "ebit", "konzernergebnis",
    "bilanz_gesamt", "eigenkapital", "verbindlichkeiten",
    "segment", "ic", "sonstige",
]


def _lade_kommentare() -> dict:
    if COMMENTS_FILE.exists():
        data = json.loads(COMMENTS_FILE.read_text(encoding="utf-8"))
        data.setdefault("zeilen_guv", {})
        data.setdefault("zeilen_bilanz", {})
        return data
    return {k: "" for k in _COMMENT_KEYS} | {"zeilen_guv": {}, "zeilen_bilanz": {}}


def _speichere_kommentare(kommentare: dict) -> None:
    COMMENTS_FILE.write_text(
        json.dumps(kommentare, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Pipeline laden
# ---------------------------------------------------------------------------

def _lm(name: str, pfad: Path):
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
# Hilfsfunktionen
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


def _build_context(guv: pd.DataFrame, bilanz: pd.DataFrame, seg_df: pd.DataFrame) -> str:
    lines = ["# Konzernabschluss Muster Holding AG 2024 (Angaben in TEUR)\n"]
    lines.append("## Konzern-GuV")
    for pos, row in guv.iterrows():
        v24, v23 = row["2024"], row["2023"]
        lines.append(f"- {pos}: {v24:,.1f} (VJ {v23:,.1f})")
    lines.append("\n## Konzern-Bilanz Aktiva")
    for _, row in bilanz[bilanz["Seite"] == "Aktiva"].iterrows():
        lines.append(f"- {row['Position']}: {row['2024']:,.1f} (VJ {row['2023']:,.1f})")
    lines.append("\n## Konzern-Bilanz Passiva")
    for _, row in bilanz[bilanz["Seite"] == "Passiva"].iterrows():
        lines.append(f"- {row['Position']}: {row['2024']:,.1f} (VJ {row['2023']:,.1f})")
    if seg_df is not None and not seg_df.empty:
        lines.append("\n## Segmentbericht")
        for _, row in seg_df.iterrows():
            lines.append(
                f"- {row['Gesellschaft']} ({row['Land']}): "
                f"Umsatz {row['Umsatz (TEUR)']:,.0f}, EBIT {row['EBIT (TEUR)']:,.0f}, "
                f"Marge {row['EBIT-Marge']:.1%}"
            )
    return "\n".join(lines)


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
                    "stichtag":     kurse.get("CHF", {}).get("stichtagskurs",    1.058),
                    "durchschnitt": kurse.get("CHF", {}).get("durchschnittskurs", 1.042),
                },
                "PLN_EUR": {
                    "stichtag":     kurse.get("PLN", {}).get("stichtagskurs",    0.233),
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

# ---------------------------------------------------------------------------
# Pipeline ausführen
# ---------------------------------------------------------------------------

guv, bilanz, daten, ic_log, min_log = _run_pipeline(chf_s, chf_d, pln_s, pln_d)

with st.sidebar:
    st.markdown("---")
    st.markdown("**⬇️ Excel-Export**")
    if st.button("Konzernabschluss generieren"):
        import io, tempfile, os, pathlib as _pl
        buf = io.BytesIO()
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
            tmp_path = _pl.Path(tmp.name)
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
# Segmentdaten vor Tabs berechnen (wird in Tab 4 + Tab 7 genutzt)
# ---------------------------------------------------------------------------

seg_rows = []
for _key, _d in daten.items():
    _g_seg = _d["guv"]
    _b_seg = _d["bilanz"]

    def _gv(pos, _gs=_g_seg):
        return float(_gs.loc[pos, "2024"]) if pos in _gs.index else 0.0

    def _bv(pos, seite="Aktiva", _bs=_b_seg):
        row = _bs[(_bs["Position"] == pos) & (_bs["Seite"] == seite)]
        return float(row["2024"].iloc[0]) if not row.empty else 0.0

    _umsatz_seg = _gv("Gesamtumsatz")
    _ebit_seg   = _gv("EBIT")
    seg_rows.append({
        "Gesellschaft":  _d["name"],
        "Land":          _d.get("land", ""),
        "Währung":       _d.get("waehrung_orig", "EUR"),
        "Beteiligung":   f"{_d.get('beteiligung', 1.0):.0%}",
        "Umsatz (TEUR)": _umsatz_seg,
        "EBIT (TEUR)":   _ebit_seg,
        "EBIT-Marge":    _ebit_seg / _umsatz_seg if _umsatz_seg else 0,
        "JÜ (TEUR)":     _gv("JAHRESÜBERSCHUSS"),
        "Bilanzsumme":   _bv("BILANZSUMME AKTIVA"),
        "Eigenkapital":  _bv("Summe Eigenkapital", "Passiva"),
    })
seg_df = pd.DataFrame(seg_rows)

# ---------------------------------------------------------------------------
# Kommentare laden
# ---------------------------------------------------------------------------

kommentare = _lade_kommentare()

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
    "📊 Konzern-GuV",
    "🏛 Konzern-Bilanz",
    "💧 Kapitalflussrechnung",
    "🗺 Segmentbericht",
    "🔗 IC-Eliminierungen",
    "📝 Analyse & Kommentare",
    "🤖 Claude fragen",
])

# ── Tab 1: GuV ──────────────────────────────────────────────────────────────
with tab1:
    st.subheader("Konzern-Gewinn- und Verlustrechnung 2024")

    col_a, col_b = st.columns([3, 2])

    with col_a:
        row_komm_guv = kommentare.get("zeilen_guv", {})
        guv_display = guv[["2024", "2023"]].copy()
        guv_display.columns = ["2024 (TEUR)", "2023 (TEUR)"]
        guv_display["Δ %"] = guv_display.apply(
            lambda r: f"{(r['2024 (TEUR)']-r['2023 (TEUR)'])/abs(r['2023 (TEUR)']):+.1%}"
            if r["2023 (TEUR)"] and abs(r["2023 (TEUR)"]) > 0.1 else "—", axis=1
        )
        guv_display.index.name = "Position"
        guv_display["Kommentar"] = guv_display.index.map(lambda p: row_komm_guv.get(p, ""))

        edited_guv = st.data_editor(
            guv_display,
            column_config={
                "2024 (TEUR)": st.column_config.NumberColumn(disabled=True, format="%.1f"),
                "2023 (TEUR)": st.column_config.NumberColumn(disabled=True, format="%.1f"),
                "Δ %":         st.column_config.TextColumn(disabled=True),
                "Kommentar":   st.column_config.TextColumn("Kommentar", width="large"),
            },
            use_container_width=True,
            height=620,
            key="editor_guv",
        )

        if st.button("💾 Kommentare speichern", key="save_guv"):
            kommentare["zeilen_guv"] = {
                pos: txt
                for pos, txt in zip(edited_guv.index, edited_guv["Kommentar"])
                if txt
            }
            _speichere_kommentare(kommentare)
            st.success("Gespeichert ✅")

    with col_b:
        st.caption("EBIT-Entwicklung")
        st.bar_chart(pd.DataFrame({"2023": [_g23("EBIT")], "2024": [_g("EBIT")]}, index=["EBIT"]).T,
                     use_container_width=True)
        st.caption("Aufwandsstruktur 2024 (TEUR)")
        st.bar_chart(pd.Series({
            "Material":  abs(_g("Materialaufwand")),
            "Personal":  abs(_g("Personalaufwand")),
            "AfA":       abs(_g("Abschreibungen (AfA)")),
            "Sonstiges": abs(_g("Sonstiger betrieblicher Aufwand")),
        }), use_container_width=True)

# ── Tab 2: Bilanz ────────────────────────────────────────────────────────────
with tab2:
    st.subheader("Konzern-Bilanz 31.12.2024")

    row_komm_bilanz = kommentare.get("zeilen_bilanz", {})

    aktiva  = bilanz[bilanz["Seite"] == "Aktiva"][["Position", "2024", "2023"]].reset_index(drop=True).copy()
    passiva = bilanz[bilanz["Seite"] == "Passiva"][["Position", "2024", "2023"]].reset_index(drop=True).copy()
    aktiva["Kommentar"]  = aktiva["Position"].map(lambda p: row_komm_bilanz.get(p, ""))
    passiva["Kommentar"] = passiva["Position"].map(lambda p: row_komm_bilanz.get(p, ""))

    _bilanz_col_cfg = {
        "Position": st.column_config.TextColumn(disabled=True),
        "2024":     st.column_config.NumberColumn(disabled=True, format="%.1f"),
        "2023":     st.column_config.NumberColumn(disabled=True, format="%.1f"),
        "Kommentar": st.column_config.TextColumn("Kommentar", width="medium"),
    }

    col_a, col_b = st.columns(2)
    with col_a:
        st.caption("AKTIVA")
        edited_aktiva = st.data_editor(
            aktiva, column_config=_bilanz_col_cfg,
            use_container_width=True, hide_index=True, key="editor_aktiva",
        )
    with col_b:
        st.caption("PASSIVA")
        edited_passiva = st.data_editor(
            passiva, column_config=_bilanz_col_cfg,
            use_container_width=True, hide_index=True, key="editor_passiva",
        )

    if st.button("💾 Kommentare speichern", key="save_bilanz"):
        new_b = {}
        for _, row in edited_aktiva.iterrows():
            if row["Kommentar"]:
                new_b[row["Position"]] = row["Kommentar"]
        for _, row in edited_passiva.iterrows():
            if row["Kommentar"]:
                new_b[row["Position"]] = row["Kommentar"]
        kommentare["zeilen_bilanz"] = new_b
        _speichere_kommentare(kommentare)
        st.success("Gespeichert ✅")

    st.caption("Passiva-Struktur 2024")
    st.bar_chart(pd.DataFrame({
        "Eigenkapital":    [_b("Summe Eigenkapital", "Passiva")],
        "Rückstellungen":  [_b("Summe Rückstellungen", "Passiva")],
        "Verbindlichkeiten": [_b("Summe Verbindlichkeiten", "Passiva")],
    }), use_container_width=True, height=160)

# ── Tab 3: KFR ───────────────────────────────────────────────────────────────
with tab3:
    st.subheader("Kapitalflussrechnung 2024 (indirekte Methode)")

    def _bd(pos):
        row = bilanz[bilanz["Position"] == pos]
        if row.empty:
            return 0.0
        v24, v23 = row["2024"].iloc[0], row["2023"].iloc[0]
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

    kfr_df = pd.DataFrame({
        "Position": [
            "I. Cashflow aus Betriebstätigkeit", "  Jahresüberschuss",
            "  + Abschreibungen", "  − Δ Vorräte", "  − Δ Forderungen L&L",
            "  + Δ Verbindlichkeiten L&L", "  = CFO",
            "II. Cashflow aus Investitionen", "  − Investitionen (Näherung)", "  = CFI",
            "III. Cashflow aus Finanzierung", "  ± Δ Bankverbindlichkeiten", "  = CFF",
            "Netto-Veränderung liquide Mittel",
        ],
        "2024 (TEUR)": [
            None, jue, afa, -d_vorr, -d_ford, d_verb, cfo,
            None, cfi, cfi,
            None, _bd("Bankverbindlichkeiten"), cff,
            netto,
        ],
    })
    TOTALS_KFR = {"  = CFO", "  = CFI", "  = CFF", "Netto-Veränderung liquide Mittel"}
    st.dataframe(
        kfr_df.style.apply(
            lambda row: ["background-color:#f0f4f8;font-weight:bold"
                         if row["Position"] in TOTALS_KFR else ""] * len(row), axis=1
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
    st.dataframe(
        seg_df.style.format({
            "Umsatz (TEUR)": "{:,.1f}", "EBIT (TEUR)": "{:,.1f}",
            "EBIT-Marge": "{:.1%}", "JÜ (TEUR)": "{:,.1f}",
            "Bilanzsumme": "{:,.1f}", "Eigenkapital": "{:,.1f}",
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

    st.markdown("### Automatische Abweichungsanalyse")
    st.caption("Positionen mit |Δ| > 15 % und |ΔTEUR| > 500 TEUR gegenüber Vorjahr")

    auffaellig = []
    for pos, row in guv.iterrows():
        v24, v23 = row["2024"], row["2023"]
        if not v23 or abs(v23) < 0.1:
            continue
        delta_abs = v24 - v23
        delta_pct = delta_abs / abs(v23)
        if abs(delta_pct) >= 0.15 and abs(delta_abs) >= 500:
            vorzeichen = "+" if delta_abs > 0 else ""
            auffaellig.append({
                "Bereich": "GuV", "Position": pos,
                "2024 (TEUR)": v24, "2023 (TEUR)": v23,
                "Δ TEUR": round(delta_abs, 1), "Δ %": delta_pct,
                "_text": (
                    f"**{pos}** ist um {vorzeichen}{delta_abs:,.0f} TEUR "
                    f"({vorzeichen}{delta_pct:.1%}) {'gestiegen' if delta_abs > 0 else 'gesunken'} "
                    f"(von {v23:,.0f} auf {v24:,.0f} TEUR)."
                ),
            })

    for _, row in bilanz.iterrows():
        pos, v24, v23 = row["Position"], row["2024"], row["2023"]
        if not v23 or abs(v23) < 0.1 or pd.isna(v23) or pd.isna(v24):
            continue
        delta_abs = v24 - v23
        delta_pct = delta_abs / abs(v23)
        if abs(delta_pct) >= 0.15 and abs(delta_abs) >= 500:
            vorzeichen = "+" if delta_abs > 0 else ""
            auffaellig.append({
                "Bereich": f"Bilanz ({row['Seite']})", "Position": pos,
                "2024 (TEUR)": v24, "2023 (TEUR)": v23,
                "Δ TEUR": round(delta_abs, 1), "Δ %": delta_pct,
                "_text": (
                    f"**{pos}** ({row['Seite']}) ist um {vorzeichen}{delta_abs:,.0f} TEUR "
                    f"({vorzeichen}{delta_pct:.1%}) {'gestiegen' if delta_abs > 0 else 'gesunken'}."
                ),
            })

    if auffaellig:
        df_auf = pd.DataFrame(auffaellig).drop(columns=["_text"])
        st.dataframe(
            df_auf.style.format({
                "2024 (TEUR)": "{:,.1f}", "2023 (TEUR)": "{:,.1f}",
                "Δ TEUR": "{:+,.1f}", "Δ %": "{:+.1%}",
            }).apply(
                lambda row: ["background-color:#fff0f0" if row["Δ TEUR"] < 0
                             else "background-color:#f0fff0"] * len(row), axis=1
            ),
            use_container_width=True, hide_index=True,
        )
        st.markdown("#### Narrativ")
        top = sorted(auffaellig, key=lambda x: abs(x["Δ TEUR"]), reverse=True)[:5]
        narrative = "Die wesentlichen Veränderungen gegenüber dem Vorjahr:\n\n"
        for item in top:
            narrative += f"- {item['_text']}\n"
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

    st.divider()

    st.markdown("### Übergreifende Kommentare")
    st.caption("Zeilenkommentare direkt in den Tabellen GuV und Bilanz eintragen.")

    felder = {
        "guv_gesamt":        ("📊 Gesamtbeurteilung GuV", "Allgemeine Einschätzung der GuV-Entwicklung …"),
        "umsatz":            ("📈 Umsatzentwicklung", "Kommentar zur Umsatzentwicklung und -treibern …"),
        "ebit":              ("⚙️ EBIT / operatives Ergebnis", "Erläuterung der EBIT-Entwicklung …"),
        "konzernergebnis":   ("💰 Konzernergebnis", "Kommentar zum Konzernjahresüberschuss …"),
        "bilanz_gesamt":     ("🏛 Gesamtbeurteilung Bilanz", "Allgemeine Einschätzung der Bilanzstruktur …"),
        "eigenkapital":      ("🏦 Eigenkapital & Minderheiten", "Kommentar zu EK-Veränderungen und Minderheitenanteilen …"),
        "verbindlichkeiten": ("📋 Verbindlichkeiten & Rückstellungen", "Kommentar zur Fremdkapitalstruktur …"),
        "segment":           ("🗺 Segmententwicklung", "Kommentar zu regionalen / gesellschaftsbezogenen Besonderheiten …"),
        "ic":                ("🔗 Intercompany", "Erläuterung der IC-Beziehungen und offener Salden …"),
        "sonstige":          ("📌 Sonstige Hinweise", "Weitere Anmerkungen, Ausblick, Risiken …"),
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

    if any(v for k, v in neue_kommentare.items()
           if k not in ("zeilen_guv", "zeilen_bilanz") and v):
        st.divider()
        st.markdown("#### Vorschau (Druckansicht)")
        for key, (label, _) in felder.items():
            txt = neue_kommentare.get(key, "")
            if txt:
                st.markdown(f"**{label}**")
                st.markdown(f"> {txt}")

# ── Tab 7: Claude fragen ─────────────────────────────────────────────────────
with tab7:
    st.subheader("🤖 Claude fragen")
    st.caption("Stelle Fragen zum Konzernabschluss – Claude antwortet auf Basis der aktuellen Zahlen.")

    _api_key = ""
    try:
        _api_key = st.secrets.get("ANTHROPIC_API_KEY", "")
    except Exception:
        pass

    if not _api_key:
        st.warning(
            "Kein API-Key gefunden. Bitte in den **Streamlit Secrets** eintragen:\n\n"
            "Settings → Secrets → `ANTHROPIC_API_KEY = \"sk-ant-...\"`"
        )
        st.stop()

    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []

    _, col_clear = st.columns([5, 1])
    with col_clear:
        if st.button("🗑 Verlauf"):
            st.session_state.chat_history = []
            st.rerun()

    _kontext = _build_context(guv, bilanz, seg_df)
    _system = (
        "Du bist ein erfahrener Konzerncontroller und Wirtschaftsprüfer. "
        "Du analysierst den Konzernabschluss der Muster Holding AG nach HGB. "
        "Antworte präzise, professionell und auf Deutsch. "
        "Alle Beträge sind in TEUR. Stichtag: 31.12.2024.\n\n"
        f"Aktuelle Konzernzahlen:\n{_kontext}"
    )

    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if prompt := st.chat_input("Frage zum Konzernabschluss …"):
        st.session_state.chat_history.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        try:
            import anthropic as _anthropic
            client = _anthropic.Anthropic(api_key=_api_key)
            with st.chat_message("assistant"):
                with st.spinner("Claude analysiert …"):
                    response = client.messages.create(
                        model="claude-opus-4-7",
                        max_tokens=1500,
                        system=_system,
                        messages=[
                            {"role": m["role"], "content": m["content"]}
                            for m in st.session_state.chat_history
                        ],
                    )
                    answer = response.content[0].text
                st.markdown(answer)
            st.session_state.chat_history.append({"role": "assistant", "content": answer})
        except Exception as e:
            st.error(f"Fehler beim API-Aufruf: {e}")

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
st.divider()
st.caption("Konzernkonsolidierung v1.0 · HGB-konform · Angaben in TEUR · Stichtag 31.12.2024")
