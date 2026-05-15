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


DOCS_DIR = Path(__file__).parent / "docs"
DOCS_DIR.mkdir(exist_ok=True)

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
IS_DUMMY = not (PROCESSED_DIR / "final.csv").exists()

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

    # ── Marker kejadian dari berita (per kategori) ──
    if not df_articles.empty:
        df_kat = df_articles[df_articles["kategori"] == key].copy()
        for _, row in df_kat.iterrows():
            try:
                lat, lon = float(row["lat"]), float(row["lon"])
            except (ValueError, TypeError):
                continue

            kab   = str(row.get("kabupaten") or "")
            judul = str(row.get("judul") or "")[:120]
            desk  = str(row.get("deskripsi") or "")[:200]
            url   = str(row.get("url") or "#")
            tgl   = str(row.get("tanggal") or "")[:16]
            src   = str(row.get("sumber") or "")

            popup_html = f"""
            <div style="
              background:#0a0a1f;color:{neon};
              font-family:'Share Tech Mono',monospace;
              font-size:12px;border:1px solid {neon};
              padding:10px;max-width:280px;
              box-shadow:0 0 12px {neon}55;
            ">
              <div style="font-weight:bold;font-size:13px;margin-bottom:6px;
                color:#ffffff;border-bottom:1px solid {neon}44;padding-bottom:4px;">
                {judul}
              </div>
              <div style="color:{neon}99;font-size:11px;margin-bottom:6px;">
                {desk}
              </div>
              <div style="font-size:10px;color:{neon}66;margin-bottom:8px;">
                {tgl} &nbsp;|&nbsp; {src}
                {'&nbsp;|&nbsp;' + kab if kab else ''}
              </div>
              <a href="{url}" target="_blank"
                 style="color:{neon};text-decoration:none;font-size:11px;
                   border:1px solid {neon};padding:2px 8px;">
                BACA SELENGKAPNYA &rarr;
              </a>
            </div>"""

            folium.CircleMarker(
                location=[lat, lon],
                radius=7,
                color=neon,
                fill=True,
                fill_color=neon,
                fill_opacity=0.85,
                weight=2,
                popup=folium.Popup(popup_html, max_width=300),
                tooltip=f"{judul[:60]}..." if len(judul) > 60 else judul,
            ).add_to(m)

    return m._repr_html_()


maps = {key: make_map(key) for key in LAYERS}

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

maps_json      = json.dumps(maps)
stats_json     = json.dumps(stats)
layers_json    = json.dumps({k: {"neon": v["neon"]} for k, v in LAYERS.items()})
sentimen_json  = json.dumps(sentimen_summary)
data_badge     = "DATA DUMMY" if IS_DUMMY else "DATA RESMI 2023"
data_badge_cls = "warn-dummy" if IS_DUMMY else "warn-live"

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
</style>
</head>
<body>

<header>
  <div class="logo">NEXUS<span style="color:var(--neon)">//</span>MAP
    <em>INDONESIA CRIME &amp; HEALTH SURVEILLANCE</em>
  </div>
  <div class="hud-right">
    <span><span class="pulse"></span>SYSTEM ONLINE</span>
    <span>34 PROVINSI</span>
    <span>{data_badge}</span>
    <span id="clk">--:--:--</span>
  </div>
</header>

<div class="main">
  <aside>
    <div class="sec">// DATA LAYER</div>
    {render_sidebar_buttons()}

    <hr class="div"/>
    <div class="sec">// STATISTIK NASIONAL</div>
    <div class="stats-grid">
      <div class="stat-card"><div class="stat-lbl">TOTAL</div><div class="stat-val" id="s-total">—</div></div>
      <div class="stat-card"><div class="stat-lbl">RATA-RATA</div><div class="stat-val" id="s-avg">—</div></div>
      <div class="stat-card"><div class="stat-lbl">TERTINGGI</div><div class="stat-val" id="s-max">—</div></div>
      <div class="stat-card"><div class="stat-lbl">TERENDAH</div><div class="stat-val" id="s-min">—</div></div>
    </div>

    <hr class="div"/>
    <div class="sec">// TOP 5 WILAYAH</div>
    <table class="top-table">
      <thead><tr><th>#</th><th>WILAYAH</th><th>KASUS</th></tr></thead>
      <tbody id="top-body"></tbody>
    </table>

    <hr class="div"/>
    <div class="sec">// TITIK KEJADIAN</div>
    <div style="display:flex;align-items:center;gap:8px;padding:6px 4px;">
      <svg width="14" height="14"><circle cx="7" cy="7" r="6" fill="var(--neon)" opacity="0.85"/></svg>
      <span style="font-size:0.7rem;color:rgba(255,255,255,0.5)">
        <span id="marker-count" style="color:var(--neon);font-family:'Orbitron',sans-serif;font-size:0.75rem">0</span>
        &nbsp;kejadian terdeteksi dari berita
      </span>
    </div>
    <div style="font-size:0.6rem;color:rgba(255,255,255,0.2);padding:0 4px 6px;">
      Klik titik di peta untuk lihat detail berita
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
      Berita: CNN Indonesia · Antara<br/>
      Sosmed: Twitter/X (sampel)
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
const MAPS     = {maps_json};
const STATS    = {stats_json};
const LAYERS   = {layers_json};
const SENTIMEN = {sentimen_json};
let blobUrl    = null;

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

function switchLayer(key, btn) {{
  const neon = LAYERS[key].neon;

  document.documentElement.style.setProperty('--neon', neon);

  document.querySelectorAll('.layer-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');

  const s = STATS[key];
  document.getElementById('s-total').textContent = s.total.toLocaleString('id-ID');
  document.getElementById('s-avg').textContent   = s.avg.toLocaleString('id-ID');
  document.getElementById('s-max').textContent   = s.max.toLocaleString('id-ID');
  document.getElementById('s-min').textContent   = s.min.toLocaleString('id-ID');

  document.getElementById('top-body').innerHTML = s.top.map(([w, k], i) =>
    `<tr>
      <td><span class="rank">${{i+1}}.</span></td>
      <td>${{w}}</td>
      <td class="td-val">${{Number(k).toLocaleString('id-ID')}}</td>
    </tr>`
  ).join('');

  updateSentimen(key);

  // Update marker count
  const mc = document.getElementById('marker-count');
  if (mc) mc.textContent = (s.markers || 0).toLocaleString('id-ID');

  if (blobUrl) URL.revokeObjectURL(blobUrl);
  blobUrl = URL.createObjectURL(new Blob([MAPS[key]], {{type:'text/html'}}));
  document.getElementById('map-frame').src = blobUrl;
}}

setInterval(() => {{
  document.getElementById('clk').textContent =
    new Date().toLocaleTimeString('id-ID', {{hour12:false}});
}}, 1000);

document.addEventListener('DOMContentLoaded', () => {{
  const firstBtn = document.querySelector('.layer-btn');
  switchLayer(firstBtn.dataset.key, firstBtn);
}});
</script>
</body>
</html>"""

out = DOCS_DIR / "index.html"
out.write_text(HTML, encoding="utf-8")
print(f"OK Peta disimpan di {out}")
