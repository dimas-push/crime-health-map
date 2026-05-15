"""
Modul visualisasi: load GeoJSON Indonesia dan buat peta Folium.
"""

import json
from pathlib import Path
from typing import Literal

import folium
import geopandas as gpd
import pandas as pd
import requests
from folium.plugins import MiniMap

# --- Konstanta path ---
DATA_DIR = Path(__file__).parent.parent / "data"
GEOJSON_DIR = DATA_DIR / "geojson"

# Sumber GeoJSON publik (geoBoundaries - CC BY 4.0)
_GEOJSON_URLS = {
    "provinsi": "https://raw.githubusercontent.com/superpikar/indonesia-geojson/master/indonesia-province-simple.json",
    "kabupaten": "https://raw.githubusercontent.com/ans-4175/peta-indonesia-geojson/master/indonesia-kota.json",
}

# Nama kolom ID wilayah di masing-masing GeoJSON
_ID_COLUMNS = {
    "provinsi": "Propinsi",
    "kabupaten": "KABKOT",
}

LevelType = Literal["provinsi", "kabupaten"]


def download_geojson(level: LevelType) -> Path:
    """
    Download GeoJSON jika belum ada di lokal, simpan ke data/geojson/.
    Mengembalikan path file yang sudah tersimpan.
    """
    GEOJSON_DIR.mkdir(parents=True, exist_ok=True)
    dest = GEOJSON_DIR / f"indonesia_{level}.geojson"

    if dest.exists():
        return dest

    url = _GEOJSON_URLS[level]
    print(f"[visualize] Mengunduh GeoJSON {level} dari {url} ...")

    response = requests.get(url, timeout=60)
    response.raise_for_status()

    dest.write_bytes(response.content)
    print(f"[visualize] Tersimpan di {dest}")
    return dest


def load_geodataframe(level: LevelType) -> gpd.GeoDataFrame:
    """Muat GeoJSON sebagai GeoDataFrame dengan CRS WGS84."""
    path = download_geojson(level)
    gdf = gpd.read_file(path)

    # Pastikan CRS WGS84 (EPSG:4326) agar kompatibel dengan Folium
    if gdf.crs is None or gdf.crs.to_epsg() != 4326:
        gdf = gdf.set_crs(epsg=4326, allow_override=True)

    return gdf


def build_base_map(
    location: list[float] | None = None,
    zoom_start: int = 5,
) -> folium.Map:
    """
    Buat peta Folium kosong terpusat di Indonesia.

    Parameters
    ----------
    location : koordinat pusat [lat, lon]. Default: tengah Indonesia.
    zoom_start : level zoom awal.
    """
    if location is None:
        # Koordinat tengah Indonesia
        location = [-2.5, 118.0]

    m = folium.Map(
        location=location,
        zoom_start=zoom_start,
        tiles="CartoDB positron",  # tile minimalis, cocok untuk data overlay
        attr="© OpenStreetMap contributors © CartoDB",
    )

    # Mini map di pojok kanan bawah untuk orientasi
    MiniMap(toggle_display=True).add_to(m)

    return m


def add_choropleth(
    m: folium.Map,
    gdf: gpd.GeoDataFrame,
    data: pd.DataFrame,
    id_col_geo: str,
    id_col_data: str,
    value_col: str,
    layer_name: str,
    legend_name: str,
    colormap: str = "YlOrRd",
) -> folium.Map:
    """
    Tambahkan layer choropleth ke peta.

    Parameters
    ----------
    m            : peta Folium target.
    gdf          : GeoDataFrame wilayah.
    data         : DataFrame berisi nilai per wilayah.
    id_col_geo   : nama kolom ID di GeoDataFrame.
    id_col_data  : nama kolom ID di DataFrame data.
    value_col    : nama kolom nilai yang akan divisualisasikan.
    layer_name   : nama layer (tampil di LayerControl).
    legend_name  : label legenda peta.
    colormap     : skema warna Brewer (default kuning-oranye-merah).
    """
    # Gabungkan data ke GeoDataFrame agar bisa dipakai Choropleth
    merged = gdf.merge(
        data[[id_col_data, value_col]],
        left_on=id_col_geo,
        right_on=id_col_data,
        how="left",
    )

    geojson_data = json.loads(merged.to_json())

    folium.Choropleth(
        geo_data=geojson_data,
        name=layer_name,
        data=merged,
        columns=[id_col_geo, value_col],
        key_on=f"feature.properties.{id_col_geo}",
        fill_color=colormap,
        fill_opacity=0.7,
        line_opacity=0.3,
        legend_name=legend_name,
        nan_fill_color="lightgrey",  # wilayah tanpa data tampil abu-abu
    ).add_to(m)

    # Tooltip saat hover
    folium.GeoJson(
        geojson_data,
        name=f"{layer_name} (tooltip)",
        style_function=lambda _: {"fillOpacity": 0, "weight": 0},
        tooltip=folium.GeoJsonTooltip(
            fields=[id_col_geo, value_col],
            aliases=["Wilayah", legend_name],
            localize=True,
        ),
    ).add_to(m)

    return m


def save_map(m: folium.Map, filename: str = "map.html") -> Path:
    """Simpan peta ke data/processed/ dan kembalikan path-nya."""
    out_dir = DATA_DIR / "processed"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / filename
    m.save(str(out_path))
    print(f"[visualize] Peta disimpan di {out_path}")
    return out_path


# ---------------------------------------------------------------------------
# Quick test — jalankan langsung: python src/visualize.py
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("Memuat GeoDataFrame provinsi ...")
    gdf_prov = load_geodataframe("provinsi")
    print(f"  {len(gdf_prov)} provinsi dimuat. Kolom: {list(gdf_prov.columns)}")

    # Data dummy: jumlah kasus acak per provinsi untuk test choropleth
    import numpy as np

    id_col = _ID_COLUMNS["provinsi"]
    dummy_data = pd.DataFrame(
        {
            "id_wilayah": gdf_prov[id_col],
            "jumlah_kasus": np.random.randint(10, 500, size=len(gdf_prov)),
        }
    )

    m = build_base_map()
    m = add_choropleth(
        m=m,
        gdf=gdf_prov,
        data=dummy_data,
        id_col_geo=id_col,
        id_col_data="id_wilayah",
        value_col="jumlah_kasus",
        layer_name="Kriminalitas Umum",
        legend_name="Jumlah Kasus",
    )
    folium.LayerControl().add_to(m)

    path = save_map(m, "test_map.html")
    print(f"Buka file ini di browser: {path}")
