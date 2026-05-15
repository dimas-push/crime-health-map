import sys
from pathlib import Path

import streamlit as st
from streamlit_folium import st_folium

# Tambahkan src/ ke path agar modul bisa diimport
sys.path.insert(0, str(Path(__file__).parent / "src"))

from visualize import build_base_map, load_geodataframe, add_choropleth, _ID_COLUMNS

import folium
import numpy as np
import pandas as pd

# --- Konfigurasi halaman ---
st.set_page_config(
    page_title="Peta Kriminalitas & Kesehatan Indonesia",
    page_icon="🗺️",
    layout="wide",
)

st.title("🗺️ Peta Kriminalitas & Kesehatan Indonesia")
st.caption("Visualisasi data kriminalitas umum, kekerasan seksual, dan penyakit menular per wilayah.")

# --- Sidebar filter ---
with st.sidebar:
    st.header("Filter")

    kategori = st.selectbox(
        "Kategori",
        ["Kriminalitas Umum", "Kekerasan Seksual", "Penyakit Menular"],
    )

    level = st.radio(
        "Level Wilayah",
        ["provinsi", "kabupaten"],
        format_func=lambda x: x.capitalize(),
    )

    tahun = st.slider("Tahun", min_value=2019, max_value=2024, value=2023)

st.info(
    f"Menampilkan: **{kategori}** · Level: **{level.capitalize()}** · Tahun: **{tahun}**  \n"
    "⚠️ Data saat ini adalah data dummy — integrasi data resmi sedang dikembangkan.",
    icon="ℹ️",
)

# --- Load GeoDataFrame ---
@st.cache_data(show_spinner="Memuat data wilayah ...")
def get_geodataframe(level: str):
    return load_geodataframe(level)

gdf = get_geodataframe(level)
id_col = _ID_COLUMNS[level]

# --- Data dummy per kategori ---
@st.cache_data(show_spinner="Memuat data kasus ...")
def get_dummy_data(level: str, kategori: str, tahun: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed=hash((level, kategori, tahun)) % 2**32)
    gdf_temp = get_geodataframe(level)
    id_col_temp = _ID_COLUMNS[level]
    return pd.DataFrame({
        "id_wilayah": gdf_temp[id_col_temp],
        "jumlah_kasus": rng.integers(10, 800, size=len(gdf_temp)),
    })

data = get_dummy_data(level, kategori, tahun)

# --- Buat peta ---
COLOR_MAP = {
    "Kriminalitas Umum": "YlOrRd",
    "Kekerasan Seksual": "PuRd",
    "Penyakit Menular": "YlGn",
}

m = build_base_map()
m = add_choropleth(
    m=m,
    gdf=gdf,
    data=data,
    id_col_geo=id_col,
    id_col_data="id_wilayah",
    value_col="jumlah_kasus",
    layer_name=kategori,
    legend_name=f"Jumlah Kasus {kategori}",
    colormap=COLOR_MAP[kategori],
)
folium.LayerControl().add_to(m)

# --- Render peta ---
col_map, col_stat = st.columns([3, 1])

with col_map:
    st_folium(m, use_container_width=True, height=580, returned_objects=[])

with col_stat:
    st.subheader("Statistik")
    st.metric("Total Kasus", f"{data['jumlah_kasus'].sum():,}")
    st.metric("Rata-rata per Wilayah", f"{data['jumlah_kasus'].mean():.0f}")
    st.metric("Tertinggi", f"{data['jumlah_kasus'].max():,}")
    st.metric("Terendah", f"{data['jumlah_kasus'].min():,}")

    st.divider()
    st.subheader("Top 5 Wilayah")
    top5 = (
        data.merge(gdf[[id_col]], left_on="id_wilayah", right_on=id_col)
        .nlargest(5, "jumlah_kasus")[["id_wilayah", "jumlah_kasus"]]
        .rename(columns={"id_wilayah": "Wilayah", "jumlah_kasus": "Kasus"})
        .reset_index(drop=True)
    )
    top5.index += 1
    st.dataframe(top5, use_container_width=True)
