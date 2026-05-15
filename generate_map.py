"""
Generate docs/index.html dengan UI cyberpunk dan peta Folium ter-embed.
Usage: python generate_map.py
"""

import sqlite3
import sys
import json
from pathlib import Path

import folium
import branca.colormap as cm
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent / "src"))
from visualize import load_geodataframe, _ID_COLUMNS
from process import process_all
from collect_official import collect_all as collect_official_all
from collect_news import collect_news
from collect_social import collect_social
from sentiment import run_sentiment_analysis

DOCS_DIR      = Path(__file__).parent / "docs"
PROCESSED_DIR = Path(__file__).parent / "data" / "processed"
DB_PATH       = PROCESSED_DIR / "crime_health.db"
DOCS_DIR.mkdir(exist_ok=True)


def load_or_build_data() -> pd.DataFrame:
    """
    Load data dari SQLite jika sudah ada,
    atau jalankan pipeline lengkap jika belum.
    """
    final_csv = PROCESSED_DIR / "final.csv"

    if final_csv.exists():
        print("[generate_map] Memuat data dari cache (final.csv) ...")
        return pd.read_csv(final_csv)

    print("[generate_map] Data belum ada, jalankan pipeline pengumpulan data ...")
    collect_official_all()
    collect_news()
    collect_social()
    df = process_all()
    run_sentiment_analysis(use_model=False)
    return df


def load_crime_detail() -> pd.DataFrame:
    """Ambil data kriminalitas detail per jenis dari SQLite."""
    if not DB_PATH.exists():
        return pd.DataFrame()
    with sqlite3.connect(DB_PATH) as conn:
        try:
            return pd.read_sql(
                "SELECT nama_provinsi, jenis_kejahatan, jumlah_kasus FROM kriminalitas_detail",
                conn,
            )
        except Exception:
            return pd.DataFrame()


def load_articles() -> pd.DataFrame:
    """Ambil artikel dengan koordinat dari SQLite untuk marker layer."""
    if not DB_PATH.exists():
        return pd.DataFrame()
    with sqlite3.connect(DB_PATH) as conn:
        try:
            return pd.read_sql(
                "SELECT judul, deskripsi, url, tanggal, sumber, kategori, "
                "provinsi, kabupaten, lat, lon FROM artikel "
                "WHERE lat IS NOT NULL AND lon IS NOT NULL",
                conn,
            )
        except Exception:
            return pd.DataFrame()


def load_sentiment_summary() -> dict:
    """Ambil ringkasan sentimen dari SQLite untuk ditampilkan di UI."""
    if not DB_PATH.exists():
        return {}

    with sqlite3.connect(DB_PATH) as conn:
        try:
            df = pd.read_sql(
                "SELECT kategori, sentimen, COUNT(*) as jumlah "
                "FROM data_sentimen "
                "WHERE kategori IS NOT NULL AND sentimen IS NOT NULL "
                "GROUP BY kategori, sentimen",
                conn,
            )
            result = {}
            for kat, grp in df.groupby("kategori"):
                result[kat] = grp.set_index("sentimen")["jumlah"].to_dict()
            return result
        except Exception:
            return {}


# ---------------------------------------------------------------------------
# Konfigurasi layer: warna neon per kategori (gelap → neon)
# ---------------------------------------------------------------------------
LAYERS = {
    "kriminalitas": {
        "label":  "KRIMINALITAS UMUM",
        "icon":   "&#9888;",
        "neon":   "#ff6b35",
        "colors": ["#0d0015", "#3d0020", "#8b0000", "#cc3300", "#ff6b35"],
    },
    "kekerasan_seksual": {
        "label":  "KEKERASAN SEKSUAL",
        "icon":   "&#128737;",
        "neon":   "#ff00ff",
        "colors": ["#0d001a", "#2d0040", "#7700aa", "#cc00cc", "#ff00ff"],
    },
    "penyakit_menular": {
        "label":  "PENYAKIT MENULAR",
        "icon":   "&#9877;",
        "neon":   "#00ff41",
        "colors": ["#001a0d", "#003320", "#006600", "#00bb33", "#00ff41"],
    },
}

# ---------------------------------------------------------------------------
# 1. Load data
# ---------------------------------------------------------------------------
print("Memuat GeoDataFrame provinsi ...")
gdf    = load_geodataframe("provinsi")
id_col = _ID_COLUMNS["provinsi"]

# Load data nyata dari pipeline; fallback dummy jika belum ada
df_final = load_or_build_data()

def _pivot(df: pd.DataFrame, kategori: str) -> pd.Series:
    sub = (
        df[df["kategori"] == kategori]
        .groupby("nama_provinsi")["jumlah_kasus"]
        .sum()
    )
    return sub

# Bangun tabel data sesuai nama provinsi di GeoDataFrame
data = pd.DataFrame({"id_wilayah": gdf[id_col]})
for kat in ["kriminalitas", "kekerasan_seksual", "penyakit_menular"]:
    pivot = _pivot(df_final, kat)
    data[kat] = data["id_wilayah"].map(pivot).fillna(0).astype(int)

sentimen_summary = load_sentiment_summary()
df_articles      = load_articles()
df_crime_detail  = load_crime_detail()
IS_DUMMY = not (PROCESSED_DIR / "final.csv").exists()

# Hitung statistik dari berita scraping (bukan data statis)
def _news_stats(kategori: str) -> dict:
    """Statistik berbasis artikel berita yang ter-geocode per provinsi."""
    if df_articles.empty:
        return {"total": 0, "top": [], "per_prov": {}}
    sub = df_articles[df_articles["kategori"] == kategori].copy()
    per_prov = (
        sub.groupby("provinsi").size().reset_index(name="jumlah")
        if "provinsi" in sub.columns else pd.DataFrame()
    )
    top5 = (
        per_prov.nlargest(5, "jumlah")[["provinsi", "jumlah"]].values.tolist()
        if not per_prov.empty else []
    )
    return {
        "total": int(len(sub)),
        "top":   [[str(r[0]), int(r[1])] for r in top5],
        "per_prov": per_prov.set_index("provinsi")["jumlah"].to_dict()
        if not per_prov.empty else {},
    }

news_stats = {k: _news_stats(k) for k in LAYERS}

# Sub-layer kriminalitas per jenis kejahatan
CRIME_TYPES = {
    "pencurian":      {"label": "PENCURIAN",       "neon": "#ff9900"},
    "narkoba":        {"label": "NARKOBA",          "neon": "#ff6b35"},
    "penipuan":       {"label": "PENIPUAN",         "neon": "#ffcc00"},
    "penganiayaan":   {"label": "PENGANIAYAAN",     "neon": "#ff4444"},
    "pembunuhan":     {"label": "PEMBUNUHAN",       "neon": "#cc0000"},
    "korupsi":        {"label": "KORUPSI",          "neon": "#ff8800"},
    "begal_curanmor": {"label": "BEGAL/CURANMOR",  "neon": "#ff5500"},
}

# ---------------------------------------------------------------------------
# 2. Build satu peta Folium per layer dengan neon colormap + marker kejadian
# ---------------------------------------------------------------------------
ICON_COLOR = {
    "kriminalitas":      "orange",
    "kekerasan_seksual": "pink",
    "penyakit_menular":  "green",
}

def make_map(key: str) -> str:
    cfg    = LAYERS[key]
    neon   = cfg["neon"]
    values = data[key]

    colormap = cm.LinearColormap(
        colors=cfg["colors"],
        vmin=values.min(),
        vmax=values.max(),
    )

    m = folium.Map(
        location=[-2.5, 118.0],
        zoom_start=5,
        tiles=None,
        zoom_control=False,
    )
    folium.TileLayer(
        tiles="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
        attr="© CartoDB",
        max_zoom=19,
    ).add_to(m)

    merged = gdf.merge(
        data[["id_wilayah", key]],
        left_on=id_col, right_on="id_wilayah", how="left",
    )
    geojson_data = json.loads(merged.to_json())

    # GeoJson dengan fill color dari colormap neon
    folium.GeoJson(
        geojson_data,
        style_function=lambda feat: {
            "fillColor":   colormap(feat["properties"].get(key) or 0),
            "fillOpacity": 0.75,
            "color":       "#0a0a1f",
            "weight":      0.8,
        },
        highlight_function=lambda _: {
            "fillColor":   neon,
            "fillOpacity": 0.35,
            "color":       neon,
            "weight":      2,
        },
        tooltip=folium.GeoJsonTooltip(
            fields=[id_col, key],
            aliases=["Wilayah", "Kasus"],
            style=(
                f"background:#0a0a1f;"
                f"color:{neon};"
                f"font-family:'Share Tech Mono',monospace;"
                f"font-size:12px;"
                f"border:1px solid {neon};"
                f"box-shadow:0 0 8px {neon}88;"
                f"border-radius:0;"
            ),
        ),
    ).add_to(m)

    return m._repr_html_()


maps = {key: make_map(key) for key in LAYERS}


def make_crime_type_map(jenis: str) -> str:
    """Buat peta choropleth per jenis kejahatan dari kriminalitas_detail."""
    cfg  = CRIME_TYPES[jenis]
    neon = cfg["neon"]

    if df_crime_detail.empty:
        return make_map("kriminalitas")

    pivot = (
        df_crime_detail[df_crime_detail["jenis_kejahatan"] == jenis]
        .groupby("nama_provinsi")["jumlah_kasus"]
        .sum()
    )
    col_data = pd.DataFrame({"id_wilayah": gdf[id_col]})
    col_data[jenis] = col_data["id_wilayah"].map(pivot).fillna(0).astype(int)

    colormap = cm.LinearColormap(
        colors=["#0a0a1f", "#1a0800", "#551500", "#aa3300", neon],
        vmin=col_data[jenis].min(),
        vmax=max(col_data[jenis].max(), 1),
    )

    m = folium.Map(location=[-2.5, 118.0], zoom_start=5, tiles=None, zoom_control=False)
    folium.TileLayer(
        tiles="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
        attr="© CartoDB", max_zoom=19,
    ).add_to(m)

    merged = gdf.merge(col_data, left_on=id_col, right_on="id_wilayah", how="left")
    geojson_data = json.loads(merged.to_json())

    folium.GeoJson(
        geojson_data,
        style_function=lambda feat: {
            "fillColor":   colormap(feat["properties"].get(jenis) or 0),
            "fillOpacity": 0.75,
            "color":       "#0a0a1f",
            "weight":      0.8,
        },
        highlight_function=lambda _: {
            "fillColor": neon, "fillOpacity": 0.35,
            "color": neon, "weight": 2,
        },
        tooltip=folium.GeoJsonTooltip(
            fields=[id_col, jenis],
            aliases=["Wilayah", cfg["label"]],
            style=(
                f"background:#0a0a1f;color:{neon};"
                f"font-family:'Share Tech Mono',monospace;font-size:12px;"
                f"border:1px solid {neon};border-radius:0;"
            ),
        ),
    ).add_to(m)
    return m._repr_html_()


crime_type_maps = {j: make_crime_type_map(j) for j in CRIME_TYPES}
crime_type_stats = {}
for jenis, cfg in CRIME_TYPES.items():
    if df_crime_detail.empty:
        crime_type_stats[jenis] = {"total": 0, "avg": 0, "max": 0, "min": 0, "top": []}
        continue
    pivot = (
        df_crime_detail[df_crime_detail["jenis_kejahatan"] == jenis]
        .groupby("nama_provinsi")["jumlah_kasus"]
        .sum()
    )
    col_data = gdf[id_col].map(pivot).fillna(0).astype(int)
    top5 = (
        df_crime_detail[df_crime_detail["jenis_kejahatan"] == jenis]
        .groupby("nama_provinsi")["jumlah_kasus"].sum()
        .nlargest(5).reset_index()
        .values.tolist()
    )
    crime_type_stats[jenis] = {
        "total": int(col_data.sum()),
        "avg":   int(col_data.mean()),
        "max":   int(col_data.max()),
        "min":   int(col_data.min()),
        "top":   [[str(r[0]), int(r[1])] for r in top5],
        "neon":  cfg["neon"],
        "label": cfg["label"],
    }

# ---------------------------------------------------------------------------
# 3. Statistik per layer
# ---------------------------------------------------------------------------
stats = {
    key: {
        "total":   int(data[key].sum()),
        "avg":     int(data[key].mean()),
        "max":     int(data[key].max()),
        "min":     int(data[key].min()),
        "top":     data.nlargest(5, key)[["id_wilayah", key]].values.tolist(),
        "markers": int(len(df_articles[df_articles["kategori"] == key]))
                   if not df_articles.empty else 0,
    }
    for key in LAYERS
}

maps_json             = json.dumps(maps)
crime_type_maps_json  = json.dumps(crime_type_maps)
crime_type_stats_json = json.dumps(crime_type_stats)
stats_json            = json.dumps(stats)
news_stats_json       = json.dumps(news_stats)
layers_json           = json.dumps({k: {"neon": v["neon"]} for k, v in LAYERS.items()})
sentimen_json         = json.dumps(sentimen_summary)
data_badge     = "DATA DUMMY" if IS_DUMMY else "DATA RESMI 2023"
data_badge_cls = "warn-dummy" if IS_DUMMY else "warn-live"

# Timestamp scraping untuk indikator status di header
_news_ts = ""
try:
    _df_ts = pd.read_csv(PROCESSED_DIR.parent / "raw" / "news.csv")
    _news_ts = str(_df_ts["scraped_at"].max()) if "scraped_at" in _df_ts.columns else ""
except Exception:
    pass
scraped_at_iso = _news_ts
total_articles = len(df_articles) if not df_articles.empty else 0
total_markers  = sum(stats[k]["markers"] for k in LAYERS)

# Serialize artikel ke JSON untuk filter waktu di JS
def _articles_to_json() -> str:
    if df_articles.empty:
        return "[]"
    cols = ["judul", "deskripsi", "url", "tanggal", "sumber", "kategori",
            "provinsi", "kabupaten", "lat", "lon"]
    existing = [c for c in cols if c in df_articles.columns]
    return df_articles[existing].to_json(orient="records", force_ascii=False)

articles_json = _articles_to_json()

# Neon per kategori (untuk marker warna)
_NEON_MAP = {k: v["neon"] for k, v in LAYERS.items()}

# ---------------------------------------------------------------------------
# 4. HTML Template
# ---------------------------------------------------------------------------
def render_sidebar_buttons() -> str:
    btns = []
    for i, (key, cfg) in enumerate(LAYERS.items()):
        active = 'active' if i == 0 else ''
        btns.append(f"""
        <button class="layer-btn {active}"
          data-key="{key}"
          data-neon="{cfg['neon']}"
          onclick="switchLayer('{key}', this)">
          <span class="icon">{cfg['icon']}</span>
          <span>{cfg['label']}</span>
        </button>""")
    return "\n".join(btns)

HTML = f"""<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>NEXUS // CRIME &amp; HEALTH MAP</title>
<link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700;900&family=Share+Tech+Mono&display=swap" rel="stylesheet"/>
<style>
  :root {{
    --bg:     #050510;
    --panel:  #08081a;
    --border: rgba(0,255,255,0.15);
    --dim:    rgba(255,255,255,0.25);
    --neon:   #00ffff;    /* default, diupdate JS */
  }}
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

  body {{
    background: var(--bg);
    color: var(--neon);
    font-family: 'Share Tech Mono', monospace;
    height: 100vh;
    overflow: hidden;
    display: flex;
    flex-direction: column;
  }}

  /* Scanline */
  body::after {{
    content: '';
    position: fixed;
    inset: 0;
    background: repeating-linear-gradient(0deg, transparent, transparent 2px,
      rgba(0,0,0,0.07) 2px, rgba(0,0,0,0.07) 4px);
    pointer-events: none;
    z-index: 9999;
  }}

  /* ── Header ── */
  header {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 8px 20px;
    background: var(--panel);
    border-bottom: 1px solid var(--neon);
    box-shadow: 0 0 18px color-mix(in srgb, var(--neon) 30%, transparent);
    flex-shrink: 0;
    z-index: 100;
    transition: border-color 0.4s, box-shadow 0.4s;
  }}
  .logo {{
    font-family: 'Orbitron', sans-serif;
    font-size: 1rem;
    font-weight: 900;
    letter-spacing: 4px;
    color: var(--neon);
    transition: color 0.4s;
  }}
  .logo em {{ font-style: normal; color: var(--dim); font-size: 0.65rem; margin-left: 10px; letter-spacing: 2px; }}
  .hud-right {{ display: flex; align-items: center; gap: 20px; font-size: 0.68rem; letter-spacing: 1px; color: var(--dim); }}
  .pulse {{
    display: inline-block; width: 7px; height: 7px; border-radius: 50%;
    background: var(--neon); box-shadow: 0 0 8px var(--neon);
    margin-right: 6px; animation: blink 1.4s infinite;
    transition: background 0.4s, box-shadow 0.4s;
  }}
  @keyframes blink {{ 0%,100%{{opacity:1}} 50%{{opacity:0.15}} }}

  /* ── Layout ── */
  .main {{ display: flex; flex: 1; overflow: hidden; }}

  /* ── Sidebar ── */
  aside {{
    width: 256px; flex-shrink: 0;
    background: var(--panel);
    border-right: 1px solid var(--border);
    display: flex; flex-direction: column;
    overflow-y: auto; padding: 14px 10px;
    gap: 0;
  }}
  aside::-webkit-scrollbar {{ width: 3px; }}
  aside::-webkit-scrollbar-thumb {{ background: var(--neon); border-radius: 2px; transition: background 0.4s; }}

  .sec {{ font-size: 0.58rem; letter-spacing: 3px; color: rgba(255,255,255,0.2);
          text-transform: uppercase; padding: 4px 4px 6px; }}

  /* Layer buttons */
  .layer-btn {{
    display: flex; align-items: center; gap: 10px;
    padding: 9px 10px; margin-bottom: 5px;
    background: transparent;
    border: 1px solid rgba(255,255,255,0.06);
    color: rgba(255,255,255,0.45);
    font-family: 'Share Tech Mono', monospace;
    font-size: 0.72rem; letter-spacing: 1px;
    cursor: pointer; text-align: left;
    transition: all 0.25s;
    position: relative;
  }}
  /* neon left bar */
  .layer-btn::before {{
    content: '';
    position: absolute; left: 0; top: 0; bottom: 0; width: 3px;
    background: transparent;
    transition: background 0.25s, box-shadow 0.25s;
  }}
  .layer-btn.active, .layer-btn:hover {{
    border-color: var(--neon);
    color: var(--neon);
    background: color-mix(in srgb, var(--neon) 6%, transparent);
  }}
  .layer-btn.active::before, .layer-btn:hover::before {{
    background: var(--neon);
    box-shadow: 0 0 8px var(--neon);
  }}

  hr.div {{ border: none; border-top: 1px solid var(--border); margin: 12px 0; }}

  /* Stats */
  .stats-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 6px; margin-bottom: 10px; }}
  .stat-card {{
    background: #0c0c22; border: 1px solid var(--border);
    padding: 9px 6px; text-align: center;
    transition: border-color 0.4s;
  }}
  .stat-lbl {{ font-size: 0.56rem; letter-spacing: 2px; color: rgba(255,255,255,0.25); text-transform: uppercase; margin-bottom: 4px; }}
  .stat-val {{
    font-family: 'Orbitron', sans-serif; font-size: 0.95rem; font-weight: 700;
    color: var(--neon); text-shadow: 0 0 10px var(--neon);
    transition: color 0.4s, text-shadow 0.4s;
  }}

  /* Top table */
  .top-table {{ width: 100%; border-collapse: collapse; font-size: 0.7rem; }}
  .top-table th {{
    font-size: 0.57rem; letter-spacing: 2px; color: rgba(255,255,255,0.2);
    text-transform: uppercase; padding: 3px 5px;
    border-bottom: 1px solid var(--border); text-align: left;
  }}
  .top-table td {{ padding: 5px 5px; border-bottom: 1px solid rgba(255,255,255,0.04); color: rgba(255,255,255,0.6); }}
  .top-table .td-val {{ color: var(--neon); text-align: right; font-family: 'Orbitron', sans-serif; font-size: 0.65rem; transition: color 0.4s; }}
  .top-table tr:hover td {{ background: color-mix(in srgb, var(--neon) 4%, transparent); }}
  .rank {{ color: rgba(255,255,255,0.2); }}

  /* ── Map area ── */
  .map-wrap {{ flex: 1; position: relative; display: flex; flex-direction: column; }}
  #map-frame {{ flex: 1; border: none; display: block; }}

  /* Corner brackets */
  .c {{ position: absolute; width: 18px; height: 18px; pointer-events: none; z-index: 10; transition: border-color 0.4s, box-shadow 0.4s; }}
  .c-tl {{ top:6px; left:6px; border-top:2px solid var(--neon); border-left:2px solid var(--neon); box-shadow:-1px -1px 6px color-mix(in srgb, var(--neon) 50%, transparent); }}
  .c-tr {{ top:6px; right:6px; border-top:2px solid var(--neon); border-right:2px solid var(--neon); box-shadow:1px -1px 6px color-mix(in srgb, var(--neon) 50%, transparent); }}
  .c-bl {{ bottom:6px; left:6px; border-bottom:2px solid var(--neon); border-left:2px solid var(--neon); box-shadow:-1px 1px 6px color-mix(in srgb, var(--neon) 50%, transparent); }}
  .c-br {{ bottom:6px; right:6px; border-bottom:2px solid var(--neon); border-right:2px solid var(--neon); box-shadow:1px 1px 6px color-mix(in srgb, var(--neon) 50%, transparent); }}

  .warn {{
    position: absolute; top: 12px; left: 50%; transform: translateX(-50%);
    font-size: 0.6rem; letter-spacing: 2px;
    padding: 3px 12px; z-index: 10; pointer-events: none; white-space: nowrap;
  }}
  .warn-dummy {{ background: rgba(255,255,0,0.06); border: 1px solid rgba(255,255,0,0.3); color: #ffff00; }}
  .warn-live  {{ background: rgba(0,255,65,0.06);  border: 1px solid rgba(0,255,65,0.3);  color: #00ff41; }}

  /* Sentimen bar */
  .sent-row {{ display:flex; align-items:center; gap:6px; margin-bottom:5px; font-size:0.67rem; }}
  .sent-label {{ width:52px; color:rgba(255,255,255,0.4); }}
  .sent-bar {{ flex:1; height:6px; background:#0d0d2a; border-radius:2px; overflow:hidden; }}
  .sent-fill {{ height:100%; border-radius:2px; transition:width 0.4s; }}
  .sent-count {{ width:24px; text-align:right; color:var(--neon); font-family:'Orbitron',sans-serif; font-size:0.62rem; }}
  .hud-br {{
    position: absolute; bottom: 16px; right: 16px;
    background: rgba(8,8,26,0.85); border: 1px solid var(--border);
    font-size: 0.6rem; letter-spacing: 2px; color: rgba(255,255,255,0.2);
    padding: 5px 12px; z-index: 10; pointer-events: none;
    backdrop-filter: blur(4px);
  }}

  /* Filter waktu */
  .tf-btn {{
    padding: 4px 8px; font-family: 'Share Tech Mono', monospace;
    font-size: 0.63rem; letter-spacing: 1px; cursor: pointer;
    background: transparent; border: 1px solid rgba(255,255,255,0.1);
    color: rgba(255,255,255,0.35); transition: all 0.2s;
  }}
  .tf-btn.active, .tf-btn:hover {{
    background: color-mix(in srgb, var(--neon) 12%, transparent);
    border-color: var(--neon); color: var(--neon);
  }}

  /* Mobile responsive */
  @media (max-width: 700px) {{
    aside {{ width: 100%; max-height: 42vh; border-right: none; border-bottom: 1px solid var(--border); }}
    .main {{ flex-direction: column; }}
    .logo em {{ display: none; }}
    .hud-right span:nth-child(2) {{ display: none; }}
  }}
</style>
</head>
<body>

<header>
  <div class="logo">NEXUS<span style="color:var(--neon)">//</span>MAP
    <em>INDONESIA CRIME &amp; HEALTH SURVEILLANCE</em>
  </div>
  <div class="hud-right">
    <span id="sys-status"><span class="pulse" id="sys-pulse"></span><span id="sys-label">MEMUAT...</span></span>
    <span>34 PROV &nbsp;|&nbsp; <span id="hud-markers">{total_markers}</span> TITIK</span>
    <span id="hud-age" title="Waktu scraping terakhir">—</span>
    <span id="clk">--:--:--</span>
  </div>
</header>

<div class="main">
  <aside>
    <div class="sec">// DATA LAYER</div>
    {render_sidebar_buttons()}

    <hr class="div"/>
    <div class="sec">// DATA ESTIMASI BPS 2023
      <span style="color:#ffaa00;font-size:0.5rem;margin-left:4px;">&#9888; STATIS</span>
    </div>
    <div style="font-size:0.58rem;color:rgba(255,180,0,0.5);padding:0 4px 6px;line-height:1.5;">
      Angka ini adalah <b style="color:#ffaa00">estimasi</b> berdasarkan<br/>
      proporsi populasi, bukan data BPS asli.
    </div>
    <div class="stats-grid">
      <div class="stat-card"><div class="stat-lbl">TOTAL</div><div class="stat-val" id="s-total">—</div></div>
      <div class="stat-card"><div class="stat-lbl">RATA-RATA</div><div class="stat-val" id="s-avg">—</div></div>
      <div class="stat-card"><div class="stat-lbl">TERTINGGI</div><div class="stat-val" id="s-max">—</div></div>
      <div class="stat-card"><div class="stat-lbl">TERENDAH</div><div class="stat-val" id="s-min">—</div></div>
    </div>
    <div style="font-size:0.6rem;color:rgba(255,255,255,0.2);padding:0 4px 4px;">
      Top 5 (estimasi BPS):
    </div>
    <table class="top-table">
      <thead><tr><th>#</th><th>WILAYAH</th><th>EST.</th></tr></thead>
      <tbody id="top-body"></tbody>
    </table>

    <hr class="div"/>
    <div class="sec">// DATA NYATA — BERITA SCRAPED
      <span style="color:#00ff41;font-size:0.5rem;margin-left:4px;">&#9679; LIVE</span>
    </div>
    <div style="font-size:0.58rem;color:rgba(0,255,65,0.5);padding:0 4px 6px;line-height:1.5;">
      Dihitung dari artikel berita ter-geocode<br/>
      (CNN, Tempo, Jawa Pos, Antara, dll.)
    </div>
    <div class="stats-grid">
      <div class="stat-card" style="grid-column:span 2">
        <div class="stat-lbl">TOTAL ARTIKEL TERDETEKSI</div>
        <div class="stat-val" id="n-total" style="font-size:1.1rem">—</div>
      </div>
    </div>
    <div style="font-size:0.6rem;color:rgba(255,255,255,0.2);padding:0 4px 4px;">
      Top 5 provinsi (dari berita):
    </div>
    <table class="top-table">
      <thead><tr><th>#</th><th>WILAYAH</th><th>BERITA</th></tr></thead>
      <tbody id="news-top-body"></tbody>
    </table>

    <hr class="div"/>
    <div class="sec">// JENIS KEJAHATAN</div>
    <div id="crime-type-panel" style="display:none">
      <div style="font-size:0.6rem;color:rgba(255,255,255,0.2);padding:2px 4px 6px;">
        Sub-kategori kriminalitas per jenis
      </div>
      <button class="crime-btn" data-jenis="" onclick="switchCrimeType('',this)"
        style="display:flex;align-items:center;gap:8px;padding:7px 10px;margin-bottom:4px;
          background:color-mix(in srgb,#ff6b35 8%,transparent);
          border:1px solid #ff6b35;color:#ff6b35;
          font-family:'Share Tech Mono',monospace;font-size:0.68rem;
          cursor:pointer;width:100%;text-align:left;">
        &#9646; SEMUA JENIS
      </button>
      {''.join(f"""<button class="crime-btn" data-jenis="{j}"
          onclick="switchCrimeType('{j}',this)"
          style="display:flex;align-items:center;gap:8px;padding:7px 10px;margin-bottom:3px;
            background:transparent;border:1px solid rgba(255,255,255,0.07);
            color:rgba(255,255,255,0.4);font-family:'Share Tech Mono',monospace;
            font-size:0.68rem;cursor:pointer;width:100%;text-align:left;
            transition:all 0.2s;" data-neon="{cfg['neon']}">
          &#9656; {cfg['label']}
        </button>""" for j, cfg in CRIME_TYPES.items())}
    </div>

    <hr class="div"/>
    <div class="sec">// TITIK KEJADIAN</div>
    <div style="display:flex;align-items:center;gap:8px;padding:6px 4px;">
      <svg width="14" height="14"><circle cx="7" cy="7" r="6" fill="var(--neon)" opacity="0.85"/></svg>
      <span style="font-size:0.7rem;color:rgba(255,255,255,0.5)">
        <span id="marker-count" style="color:var(--neon);font-family:'Orbitron',sans-serif;font-size:0.75rem">0</span>
        &nbsp;kejadian terdeteksi
      </span>
    </div>
    <div style="font-size:0.6rem;color:rgba(255,255,255,0.2);padding:0 4px 4px;">
      Filter rentang waktu:
    </div>
    <div style="display:flex;gap:4px;flex-wrap:wrap;padding:0 2px 6px;">
      <button class="tf-btn"        data-days="7"   onclick="setTimeFilter(7,this)">7H</button>
      <button class="tf-btn"        data-days="30"  onclick="setTimeFilter(30,this)">30H</button>
      <button class="tf-btn"        data-days="90"  onclick="setTimeFilter(90,this)">90H</button>
      <button class="tf-btn active" data-days="0"   onclick="setTimeFilter(0,this)">SEMUA</button>
    </div>
    <div style="font-size:0.6rem;color:rgba(255,255,255,0.2);padding:0 4px 6px;">
      Klik titik di peta untuk detail berita
    </div>

    <hr class="div"/>
    <div class="sec">// ANALISIS SENTIMEN</div>
    <div id="sent-panel">
      <div class="sent-row"><span class="sent-label">NEGATIF</span><div class="sent-bar"><div class="sent-fill" id="sent-neg" style="background:#ff4444;width:0%"></div></div><span class="sent-count" id="sent-neg-n">0</span></div>
      <div class="sent-row"><span class="sent-label">NETRAL</span><div class="sent-bar"><div class="sent-fill" id="sent-net" style="background:#888888;width:0%"></div></div><span class="sent-count" id="sent-net-n">0</span></div>
      <div class="sent-row"><span class="sent-label">POSITIF</span><div class="sent-bar"><div class="sent-fill" id="sent-pos" style="background:#00ff41;width:0%"></div></div><span class="sent-count" id="sent-pos-n">0</span></div>
    </div>

    <hr class="div"/>
    <div class="sec" style="color:rgba(255,255,255,0.1)">// SUMBER: BPS · KEMENKES · SIMFONI-PPA</div>
    <div style="font-size:0.58rem;color:rgba(255,255,255,0.15);line-height:1.7;padding:2px 4px">
      Berita: Google News · CNN · Tempo<br/>
      Antara · Republika · Jawa Pos<br/>
      Sosmed: Telegram · YouTube
    </div>
  </aside>

  <div class="map-wrap">
    <div class="c c-tl"></div>
    <div class="c c-tr"></div>
    <div class="c c-bl"></div>
    <div class="c c-br"></div>
    <div class="warn {data_badge_cls}">&#9888; {data_badge}</div>
    <iframe id="map-frame" src="about:blank"></iframe>
    <div class="hud-br">WGS84 · EPSG:4326 · &copy; NEXUS MAP SYS</div>
  </div>
</div>

<script>
const MAPS            = {maps_json};
const CRIME_TYPE_MAPS = {crime_type_maps_json};
const CRIME_TYPE_STATS = {crime_type_stats_json};
const STATS      = {stats_json};
const NEWS_STATS = {news_stats_json};
const LAYERS     = {layers_json};
const SENTIMEN   = {sentimen_json};
const ARTICLES   = {articles_json};
const NEON_MAP   = {json.dumps(_NEON_MAP)};
let blobUrl    = null;
let currentLayer = 'kriminalitas';

function updateSentimen(key) {{
  const s   = SENTIMEN[key] || {{}};
  const neg = s['negatif'] || 0;
  const net = s['netral']  || 0;
  const pos = s['positif'] || 0;
  const total = neg + net + pos || 1;

  document.getElementById('sent-neg').style.width   = (neg/total*100) + '%';
  document.getElementById('sent-net').style.width   = (net/total*100) + '%';
  document.getElementById('sent-pos').style.width   = (pos/total*100) + '%';
  document.getElementById('sent-neg-n').textContent = neg;
  document.getElementById('sent-net-n').textContent = net;
  document.getElementById('sent-pos-n').textContent = pos;
}}

function loadMap(html) {{
  if (blobUrl) URL.revokeObjectURL(blobUrl);
  blobUrl = URL.createObjectURL(new Blob([html], {{type:'text/html'}}));
  document.getElementById('map-frame').src = blobUrl;
}}

function updateStats(s, neon, key) {{
  if (neon) document.documentElement.style.setProperty('--neon', neon);
  document.getElementById('s-total').textContent = (s.total||0).toLocaleString('id-ID');
  document.getElementById('s-avg').textContent   = (s.avg||0).toLocaleString('id-ID');
  document.getElementById('s-max').textContent   = (s.max||0).toLocaleString('id-ID');
  document.getElementById('s-min').textContent   = (s.min||0).toLocaleString('id-ID');
  document.getElementById('top-body').innerHTML  = (s.top||[]).map(([w,k],i)=>
    `<tr><td><span class="rank">${{i+1}}.</span></td><td>${{w}}</td>
     <td class="td-val">${{Number(k).toLocaleString('id-ID')}}</td></tr>`
  ).join('');

  // Panel data nyata dari berita
  if (key && NEWS_STATS[key]) {{
    const ns = NEWS_STATS[key];
    document.getElementById('n-total').textContent = (ns.total||0).toLocaleString('id-ID');
    document.getElementById('news-top-body').innerHTML = (ns.top||[]).map(([w,k],i)=>
      `<tr><td><span class="rank">${{i+1}}.</span></td><td>${{w}}</td>
       <td class="td-val">${{Number(k).toLocaleString('id-ID')}}</td></tr>`
    ).join('') || '<tr><td colspan="3" style="color:rgba(255,255,255,0.2);font-size:0.65rem;padding:6px">Belum ada data</td></tr>';
  }}
}}

function switchCrimeType(jenis, btn) {{
  document.querySelectorAll('.crime-btn').forEach(b => {{
    b.style.background = 'transparent';
    b.style.borderColor = 'rgba(255,255,255,0.07)';
    b.style.color = 'rgba(255,255,255,0.4)';
  }});
  const neon = btn.dataset.neon || LAYERS['kriminalitas'].neon;
  btn.style.background = `color-mix(in srgb,${{neon}} 10%,transparent)`;
  btn.style.borderColor = neon;
  btn.style.color = neon;

  if (!jenis) {{
    updateStats(STATS['kriminalitas'], LAYERS['kriminalitas'].neon, 'kriminalitas');
    document.documentElement.style.setProperty('--neon', LAYERS['kriminalitas'].neon);
    buildMapWithFilter('kriminalitas', currentDays);
  }} else {{
    const s = CRIME_TYPE_STATS[jenis] || {{}};
    updateStats(s, s.neon || neon, null);
    if (blobUrl) URL.revokeObjectURL(blobUrl);
    blobUrl = URL.createObjectURL(new Blob([CRIME_TYPE_MAPS[jenis]||''], {{type:'text/html'}}));
    document.getElementById('map-frame').src = blobUrl;
  }}
}}

function switchLayer(key, btn) {{
  currentKey = key;
  const neon = LAYERS[key].neon;
  document.documentElement.style.setProperty('--neon', neon);

  document.querySelectorAll('.layer-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');

  const crimePanel = document.getElementById('crime-type-panel');
  if (crimePanel) crimePanel.style.display = key === 'kriminalitas' ? 'block' : 'none';

  const s = STATS[key];
  updateStats(s, neon, key);
  updateSentimen(key);

  buildMapWithFilter(key, currentDays);

  if (key === 'kriminalitas') {{
    const firstCrimeBtn = document.querySelector('.crime-btn');
    if (firstCrimeBtn) {{
      firstCrimeBtn.style.background = `color-mix(in srgb,${{neon}} 8%,transparent)`;
      firstCrimeBtn.style.borderColor = neon;
      firstCrimeBtn.style.color = neon;
    }}
    document.querySelectorAll('.crime-btn:not(:first-child)').forEach(b => {{
      b.style.background = 'transparent';
      b.style.borderColor = 'rgba(255,255,255,0.07)';
      b.style.color = 'rgba(255,255,255,0.4)';
    }});
  }}
}}

// ── Jam digital ──
setInterval(() => {{
  document.getElementById('clk').textContent =
    new Date().toLocaleTimeString('id-ID', {{hour12:false}});
}}, 1000);

// ── Status sistem berdasarkan usia data ──
const SCRAPED_AT = "{scraped_at_iso}";

function updateSystemStatus() {{
  const label = document.getElementById('sys-label');
  const pulse = document.getElementById('sys-pulse');
  const ageEl = document.getElementById('hud-age');
  if (!SCRAPED_AT) {{
    label.textContent = 'NO DATA';
    pulse.style.background = '#ff4444';
    pulse.style.boxShadow  = '0 0 8px #ff4444';
    ageEl.textContent = '—';
    return;
  }}

  const scraped = new Date(SCRAPED_AT);
  const now     = new Date();
  const diffMs  = now - scraped;
  const diffMin = Math.floor(diffMs / 60000);
  const diffHr  = Math.floor(diffMin / 60);
  const diffDay = Math.floor(diffHr / 24);

  // Format usia data
  let ageStr;
  if (diffMin < 1)       ageStr = 'BARU SAJA';
  else if (diffMin < 60) ageStr = diffMin + ' MNT LALU';
  else if (diffHr < 24)  ageStr = diffHr + ' JAM LALU';
  else                   ageStr = diffDay + ' HARI LALU';
  ageEl.textContent = ageStr;
  ageEl.title = 'Scraping: ' + scraped.toLocaleString('id-ID');

  // Status & warna
  if (diffHr < 6) {{
    label.textContent = 'SYSTEM ONLINE';
    pulse.style.background = '#00ff41';
    pulse.style.boxShadow  = '0 0 8px #00ff41';
    label.style.color      = '#00ff41';
  }} else if (diffHr < 24) {{
    label.textContent = 'DATA PERLU REFRESH';
    pulse.style.background = '#ffaa00';
    pulse.style.boxShadow  = '0 0 8px #ffaa00';
    label.style.color      = '#ffaa00';
    pulse.style.animationDuration = '0.7s';
  }} else {{
    label.textContent = 'DATA USANG';
    pulse.style.background = '#ff4444';
    pulse.style.boxShadow  = '0 0 8px #ff4444';
    label.style.color      = '#ff4444';
    pulse.style.animationDuration = '0.3s';
  }}
}}

// Update status setiap menit
updateSystemStatus();
setInterval(updateSystemStatus, 60000);

// ── Filter waktu & rebuild peta dengan marker ──
let currentDays = 0;   // default: semua artikel
let currentKey  = 'kriminalitas';

function parseArticleDate(tanggal) {{
  if (!tanggal) return null;
  try {{ return new Date(tanggal); }} catch(e) {{ return null; }}
}}

function buildMapWithFilter(key, days) {{
  const neon   = LAYERS[key] ? LAYERS[key].neon : NEON_MAP[key] || '#00ffff';
  const cutoff = days > 0 ? new Date(Date.now() - days * 86400000) : null;

  const filtered = ARTICLES.filter(a => {{
    if (a.kategori !== key) return false;
    if (!a.lat || !a.lon)  return false;
    if (cutoff) {{
      const d = parseArticleDate(a.tanggal);
      if (d && d < cutoff) return false;
    }}
    return true;
  }});

  document.getElementById('marker-count').textContent =
    filtered.length.toLocaleString('id-ID');

  // Bangun script marker — pecah tag </script> agar browser tidak salah parse
  // Teknik: '<' + '/script>' mencegah premature termination
  const _open  = '<' + 'script>';
  const _close = '<' + '/script>';
  const markerScript = _open + `
(function() {{
  var _neon = "${{neon}}";
  var _articles = ${{JSON.stringify(filtered)}};
  function esc(s) {{
    return String(s||'')
      .replace(/&/g,'&amp;').replace(/</g,'&lt;')
      .replace(/>/g,'&gt;').replace(/"/g,'&quot;')
      .replace(/'/g,'&#39;');
  }}
  function addMarkers(lmap) {{
    var layer = L.layerGroup().addTo(lmap);
    _articles.forEach(function(a) {{
      var c = L.circleMarker([a.lat, a.lon], {{
        radius:7, color:_neon, fillColor:_neon, fillOpacity:0.85, weight:2
      }});
      var judul = esc(String(a.judul||'').slice(0,120));
      var desk  = esc(String(a.deskripsi||'').slice(0,200));
      var tgl   = esc(String(a.tanggal||'').slice(0,16));
      var src   = esc(String(a.sumber||''));
      var kab   = esc(String(a.kabupaten||''));
      var url   = esc(String(a.url||'#'));
      var meta  = tgl + (src?' | '+src:'') + (kab?' | '+kab:'');
      var popup =
        '<div style="background:#0a0a1f;color:'+_neon+';font-family:monospace;' +
        'font-size:12px;border:1px solid '+_neon+';padding:10px;max-width:280px;' +
        'box-shadow:0 0 12px '+_neon+'55;">' +
        '<div style="font-weight:bold;font-size:13px;margin-bottom:6px;color:#fff;' +
        'border-bottom:1px solid '+_neon+'44;padding-bottom:4px;">'+judul+'</div>' +
        '<div style="color:'+_neon+'99;font-size:11px;margin-bottom:6px;">'+desk+'</div>' +
        '<div style="font-size:10px;color:'+_neon+'66;margin-bottom:8px;">'+meta+'</div>' +
        '<a href="'+url+'" target="_blank" style="color:'+_neon+';text-decoration:none;' +
        'font-size:11px;border:1px solid '+_neon+';padding:2px 8px;">' +
        'BACA SELENGKAPNYA &#8594;</a></div>';
      var tipTeks = esc(String(a.judul||'').slice(0,60));
      c.bindPopup(popup, {{maxWidth:300}});
      c.bindTooltip(tipTeks + (String(a.judul||'').length>60?'...':''));
      layer.addLayer(c);
    }});
  }}
  function findLeafletMap() {{
    for (var k in window) {{
      try {{
        var v = window[k];
        if (v && typeof v === 'object' && typeof v.getCenter === 'function' && v._leaflet_id) {{
          return v;
        }}
      }} catch(e) {{}}
    }}
    return null;
  }}
  var _tries = 0;
  function tryAddMarkers() {{
    var lmap = findLeafletMap();
    if (lmap) {{ addMarkers(lmap); return; }}
    if (++_tries < 20) {{ setTimeout(tryAddMarkers, 300); }}
  }}
  tryAddMarkers();
}})();
` + _close;

  // Inject marker script ke base map HTML dan buat blob baru
  const baseHtml = MAPS[key] || '';
  const fullHtml = baseHtml.replace('</body>', markerScript + '</body>');

  if (blobUrl) URL.revokeObjectURL(blobUrl);
  blobUrl = URL.createObjectURL(new Blob([fullHtml], {{type:'text/html'}}));
  document.getElementById('map-frame').src = blobUrl;
}}

function setTimeFilter(days, btn) {{
  document.querySelectorAll('.tf-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  currentDays = days;
  buildMapWithFilter(currentKey, days);
}}

document.addEventListener('DOMContentLoaded', () => {{
  const firstBtn = document.querySelector('.layer-btn');
  if (firstBtn) switchLayer(firstBtn.dataset.key, firstBtn);
  updateSystemStatus();
}});
</script>
</body>
</html>"""

out = DOCS_DIR / "index.html"
out.write_text(HTML, encoding="utf-8")
print(f"OK Peta disimpan di {out}")
