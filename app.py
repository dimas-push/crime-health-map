"""
Dashboard Streamlit — alternatif interaktif selain GitHub Pages.
Jalankan: streamlit run app.py
"""

import sqlite3
import sys
from pathlib import Path

import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

sys.path.insert(0, str(Path(__file__).parent / "src"))
from visualize import load_geodataframe, _ID_COLUMNS
from sentiment import get_sentimen_summary

ROOT          = Path(__file__).parent
PROCESSED_DIR = ROOT / "data" / "processed"
DB_PATH       = PROCESSED_DIR / "crime_health.db"
FINAL_CSV     = PROCESSED_DIR / "final.csv"

st.set_page_config(
    page_title="Peta Kriminalitas & Kesehatan Indonesia",
    page_icon="🗺",
    layout="wide",
)

# ── CSS cyberpunk minimal ──────────────────────────────────────────────────
st.markdown("""
<style>
  [data-testid="stAppViewContainer"] { background: #050510; }
  [data-testid="stSidebar"]          { background: #08081a; border-right: 1px solid #00ffff22; }
  h1, h2, h3                         { font-family: 'Courier New', monospace; color: #00ffff; }
  .stMetric label                    { color: #ffffff88 !important; font-size: 0.7rem; }
  .stMetric [data-testid="stMetricValue"] { color: #00ffff; font-family: monospace; }
</style>
""", unsafe_allow_html=True)

st.title("NEXUS // CRIME & HEALTH MAP")
st.caption("Visualisasi kriminalitas, kekerasan seksual, dan penyakit menular per provinsi Indonesia.")

# ── Sidebar ────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Filter")
    kategori = st.selectbox("Kategori", [
        "kriminalitas", "kekerasan_seksual", "penyakit_menular"
    ], format_func=lambda x: x.replace("_", " ").title())

    level = st.radio("Level Wilayah", ["provinsi"],
                     format_func=lambda x: x.capitalize())

    st.divider()
    if st.button("Refresh Data Pipeline", use_container_width=True):
        import subprocess
        with st.spinner("Menjalankan pipeline ..."):
            subprocess.run([sys.executable, str(ROOT / "run_all.py"),
                            "--skip-collect"], check=False)
        st.success("Pipeline selesai!")
        st.cache_data.clear()

# ── Load data ──────────────────────────────────────────────────────────────
@st.cache_data(show_spinner="Memuat data wilayah ...")
def get_gdf(level: str):
    return load_geodataframe(level)

@st.cache_data(show_spinner="Memuat data kasus ...")
def get_final() -> pd.DataFrame:
    if FINAL_CSV.exists():
        return pd.read_csv(FINAL_CSV)
    return pd.DataFrame()

gdf      = get_gdf(level)
id_col   = _ID_COLUMNS[level]
df_final = get_final()

if df_final.empty:
    st.warning("Data belum tersedia. Jalankan `python run_all.py` terlebih dahulu.")
    st.stop()

# Filter data kategori yang dipilih
df_kat = (
    df_final[df_final["kategori"] == kategori]
    .groupby("nama_provinsi")["jumlah_kasus"]
    .sum()
    .reset_index()
)

# ── Baris metrik ──────────────────────────────────────────────────────────
c1, c2, c3, c4 = st.columns(4)
c1.metric("Total Kasus",        f"{df_kat['jumlah_kasus'].sum():,}")
c2.metric("Rata-rata / Provinsi", f"{df_kat['jumlah_kasus'].mean():,.0f}")
c3.metric("Tertinggi",          f"{df_kat['jumlah_kasus'].max():,}")
c4.metric("Terendah",           f"{df_kat['jumlah_kasus'].min():,}")

# ── Peta ──────────────────────────────────────────────────────────────────
import branca.colormap as cm
import json

COLOR_MAP = {
    "kriminalitas":      ["#0d0015", "#3d0020", "#8b0000", "#cc3300", "#ff6b35"],
    "kekerasan_seksual": ["#0d001a", "#2d0040", "#7700aa", "#cc00cc", "#ff00ff"],
    "penyakit_menular":  ["#001a0d", "#003320", "#006600", "#00bb33", "#00ff41"],
}
NEON = {
    "kriminalitas": "#ff6b35",
    "kekerasan_seksual": "#ff00ff",
    "penyakit_menular": "#00ff41",
}

neon     = NEON[kategori]
colormap = cm.LinearColormap(
    colors=COLOR_MAP[kategori],
    vmin=df_kat["jumlah_kasus"].min(),
    vmax=df_kat["jumlah_kasus"].max(),
)
pivot = df_kat.set_index("nama_provinsi")["jumlah_kasus"]

merged = gdf.copy()
merged["jumlah_kasus"] = merged[id_col].map(pivot).fillna(0).astype(int)
geojson_data = json.loads(merged.to_json())

m = folium.Map(location=[-2.5, 118.0], zoom_start=5, tiles=None)
folium.TileLayer(
    tiles="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
    attr="© CartoDB", max_zoom=19,
).add_to(m)

folium.GeoJson(
    geojson_data,
    style_function=lambda feat: {
        "fillColor":   colormap(feat["properties"].get("jumlah_kasus") or 0),
        "fillOpacity": 0.75,
        "color":       "#0a0a1f",
        "weight":      0.8,
    },
    highlight_function=lambda _: {
        "fillColor": neon, "fillOpacity": 0.35,
        "color": neon, "weight": 2,
    },
    tooltip=folium.GeoJsonTooltip(
        fields=[id_col, "jumlah_kasus"],
        aliases=["Provinsi", "Jumlah Kasus"],
    ),
).add_to(m)

col_map, col_side = st.columns([3, 1])
with col_map:
    st_folium(m, use_container_width=True, height=520, returned_objects=[])

with col_side:
    st.subheader("Top 10 Provinsi")
    top10 = df_kat.nlargest(10, "jumlah_kasus").reset_index(drop=True)
    top10.index += 1
    top10.columns = ["Provinsi", "Kasus"]
    st.dataframe(top10, use_container_width=True, height=340)

    st.subheader("Sentimen Media")
    df_sent = get_sentimen_summary()
    if not df_sent.empty:
        df_k = df_sent[df_sent["kategori"] == kategori]
        for _, row in df_k.iterrows():
            st.write(f"**{row['sentimen'].capitalize()}**: {row['jumlah']}")
    else:
        st.caption("Belum ada data sentimen.")
