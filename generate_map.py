"""
Jalankan script ini untuk generate docs/index.html dari data terbaru.
Usage: python generate_map.py
"""

import sys
import json
from pathlib import Path

import folium
import numpy as np
import pandas as pd
from folium.plugins import MiniMap

sys.path.insert(0, str(Path(__file__).parent / "src"))
from visualize import load_geodataframe, build_base_map, add_choropleth, _ID_COLUMNS

DOCS_DIR = Path(__file__).parent / "docs"
DOCS_DIR.mkdir(exist_ok=True)

# --- Load GeoDataFrame provinsi ---
print("Memuat GeoDataFrame provinsi ...")
gdf = load_geodataframe("provinsi")
id_col = _ID_COLUMNS["provinsi"]

# --- Data dummy (ganti dengan data nyata nanti) ---
rng = np.random.default_rng(seed=42)
data = pd.DataFrame({
    "id_wilayah": gdf[id_col],
    "kriminalitas": rng.integers(50, 800, size=len(gdf)),
    "kekerasan_seksual": rng.integers(10, 300, size=len(gdf)),
    "penyakit_menular": rng.integers(20, 600, size=len(gdf)),
})

# --- Buat peta dengan 3 layer choropleth ---
m = build_base_map()

layer_config = [
    ("kriminalitas",      "Kriminalitas Umum",    "YlOrRd"),
    ("kekerasan_seksual", "Kekerasan Seksual",     "PuRd"),
    ("penyakit_menular",  "Penyakit Menular",      "YlGn"),
]

for col, label, colormap in layer_config:
    m = add_choropleth(
        m=m,
        gdf=gdf,
        data=data,
        id_col_geo=id_col,
        id_col_data="id_wilayah",
        value_col=col,
        layer_name=label,
        legend_name=f"Jumlah Kasus {label}",
        colormap=colormap,
    )

folium.LayerControl(collapsed=False).add_to(m)

# --- Simpan sebagai docs/index.html ---
out = DOCS_DIR / "index.html"
m.save(str(out))
print(f"Peta disimpan di {out}")
print("Sekarang jalankan: git add docs/index.html && git push")
