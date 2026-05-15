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

DATA_DIR    = Path(__file__).parent.parent / "data"
GEOJSON_DIR = DATA_DIR / "geojson"

# Kandidat URL diurutkan dari yang paling akurat (34 provinsi, nama BPS)
_GEOJSON_URLS = {
    "provinsi": [
        "https://raw.githubusercontent.com/rizki-ramadhan-alt/geojson-indonesia/main/indonesia-provinces.geojson",
        "https://raw.githubusercontent.com/superpikar/indonesia-geojson/master/indonesia-province-simple.json",
    ],
    "kabupaten": [
        "https://raw.githubusercontent.com/ans-4175/peta-indonesia-geojson/master/indonesia-kota.json",
    ],
}

# Kolom ID yang dicoba per level (berbeda antar sumber GeoJSON)
_ID_COLUMN_CANDIDATES = {
    "provinsi":  ["nama", "PROVINSI", "province", "Propinsi", "NAME_1"],
    "kabupaten": ["KABKOT", "nama", "NAME_2", "kabupaten"],
}

# ---------------------------------------------------------------------------
# Normalisasi nama GeoJSON → nama resmi BPS
# Mencakup semua variasi ejaan, huruf kapital, singkatan, dan nama lama
# ---------------------------------------------------------------------------
_GEO_TO_BPS: dict[str, str] = {
    # Nama lama / ejaan salah
    "irian jaya timur":          "Papua",
    "irian jaya tengah":         "Papua",
    "irian jaya barat":          "Papua Barat",
    "papua barat daya":          "Papua Barat",
    "probanten":                 "Banten",
    "di. aceh":                  "Aceh",
    "daerah istimewa aceh":      "Aceh",
    "nangroe aceh darussalam":   "Aceh",
    "nanggroe aceh darussalam":  "Aceh",
    "nusatenggara barat":        "Nusa Tenggara Barat",
    "nusa tenggara barat":       "Nusa Tenggara Barat",
    "nusa tenggara timur":       "Nusa Tenggara Timur",
    "daerah istimewa yogyakarta": "DI Yogyakarta",
    "di yogyakarta":             "DI Yogyakarta",
    "d.i. yogyakarta":           "DI Yogyakarta",
    "dki jakarta":               "DKI Jakarta",
    "jakarta":                   "DKI Jakarta",
    "bangka belitung":           "Kepulauan Bangka Belitung",
    "kepulauan bangka belitung": "Kepulauan Bangka Belitung",
    "kepulauan riau":            "Kepulauan Riau",
    "kalimantan utara":          "Kalimantan Utara",
    "sulawesi barat":            "Sulawesi Barat",
    # Nama standar (title case & upper) → BPS
    "aceh":               "Aceh",
    "sumatera utara":     "Sumatera Utara",
    "sumatera barat":     "Sumatera Barat",
    "riau":               "Riau",
    "jambi":              "Jambi",
    "sumatera selatan":   "Sumatera Selatan",
    "bengkulu":           "Bengkulu",
    "lampung":            "Lampung",
    "banten":             "Banten",
    "jawa barat":         "Jawa Barat",
    "jawa tengah":        "Jawa Tengah",
    "jawa timur":         "Jawa Timur",
    "bali":               "Bali",
    "kalimantan barat":   "Kalimantan Barat",
    "kalimantan tengah":  "Kalimantan Tengah",
    "kalimantan selatan": "Kalimantan Selatan",
    "kalimantan timur":   "Kalimantan Timur",
    "sulawesi utara":     "Sulawesi Utara",
    "sulawesi tengah":    "Sulawesi Tengah",
    "sulawesi selatan":   "Sulawesi Selatan",
    "sulawesi tenggara":  "Sulawesi Tenggara",
    "gorontalo":          "Gorontalo",
    "maluku":             "Maluku",
    "maluku utara":       "Maluku Utara",
    "papua":              "Papua",
}

LevelType = Literal["provinsi", "kabupaten"]


def _normalize_geo_name(nama: str) -> str:
    """Normalisasi nama wilayah dari GeoJSON ke nama resmi BPS."""
    key = str(nama).strip().lower()
    return _GEO_TO_BPS.get(key, nama.title())


def _detect_id_column(gdf: gpd.GeoDataFrame, level: LevelType) -> str:
    """Deteksi otomatis kolom ID dari GeoDataFrame."""
    for candidate in _ID_COLUMN_CANDIDATES[level]:
        if candidate in gdf.columns:
            return candidate
    # Fallback: kolom string pertama selain geometry
    for col in gdf.columns:
        if col != "geometry" and gdf[col].dtype == object:
            return col
    raise ValueError(f"Tidak dapat menemukan kolom ID di GeoDataFrame: {list(gdf.columns)}")


def download_geojson(level: LevelType) -> Path:
    """
    Download GeoJSON dari daftar URL kandidat (fallback ke berikutnya jika gagal).
    Simpan ke data/geojson/ dan kembalikan path.
    """
    GEOJSON_DIR.mkdir(parents=True, exist_ok=True)
    dest = GEOJSON_DIR / f"indonesia_{level}.geojson"

    if dest.exists():
        return dest

    headers = {"User-Agent": "Mozilla/5.0 (compatible; crime-health-map/1.0)"}
    for url in _GEOJSON_URLS[level]:
        print(f"[visualize] Mengunduh GeoJSON {level} dari {url} ...")
        try:
            resp = requests.get(url, headers=headers, timeout=60)
            resp.raise_for_status()
            dest.write_bytes(resp.content)
            print(f"[visualize] Tersimpan di {dest}")
            return dest
        except requests.RequestException as e:
            print(f"[visualize] Gagal ({e}), coba URL berikutnya ...")

    raise RuntimeError(f"Semua URL GeoJSON {level} gagal diakses.")


def load_geodataframe(level: LevelType) -> gpd.GeoDataFrame:
    """
    Muat GeoJSON sebagai GeoDataFrame dengan CRS WGS84.
    Tambahkan kolom 'nama_bps' dengan nama resmi yang sudah dinormalisasi.
    """
    path = download_geojson(level)
    gdf  = gpd.read_file(path)

    if gdf.crs is None or gdf.crs.to_epsg() != 4326:
        gdf = gdf.set_crs(epsg=4326, allow_override=True)

    id_col = _detect_id_column(gdf, level)

    # Tambahkan kolom nama_bps yang sudah dinormalisasi
    gdf["nama_bps"] = gdf[id_col].apply(_normalize_geo_name)

    return gdf


# Kolom yang dipakai sebagai key join (setelah normalisasi)
_ID_COLUMNS = {
    "provinsi":  "nama_bps",
    "kabupaten": "nama_bps",
}


def build_base_map(
    location: list[float] | None = None,
    zoom_start: int = 5,
) -> folium.Map:
    """Buat peta Folium kosong terpusat di Indonesia."""
    if location is None:
        location = [-2.5, 118.0]

    m = folium.Map(
        location=location,
        zoom_start=zoom_start,
        tiles="CartoDB positron",
        attr="© OpenStreetMap contributors © CartoDB",
    )
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
    """Tambahkan layer choropleth ke peta."""
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
        nan_fill_color="lightgrey",
    ).add_to(m)

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
    """Simpan peta ke data/processed/."""
    out_dir  = DATA_DIR / "processed"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / filename
    m.save(str(out_path))
    print(f"[visualize] Peta disimpan di {out_path}")
    return out_path


if __name__ == "__main__":
    gdf = load_geodataframe("provinsi")
    print(f"{len(gdf)} wilayah dimuat.")
    print("Sampel nama_bps:", gdf["nama_bps"].head(8).tolist())
    print("Kolom tersedia:", [c for c in gdf.columns if c != "geometry"])
