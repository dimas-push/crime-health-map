"""
Generate docs/index.html dengan UI cyberpunk dan peta Folium ter-embed.
Usage: python generate_map.py
"""

import sys
import json
from pathlib import Path

import folium
import branca.colormap as cm
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent / "src"))
from visualize import load_geodataframe, _ID_COLUMNS

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
gdf = load_geodataframe("provinsi")
id_col = _ID_COLUMNS["provinsi"]

rng = np.random.default_rng(seed=42)
data = pd.DataFrame({
    "id_wilayah":        gdf[id_col],
    "kriminalitas":      rng.integers(50,  800, size=len(gdf)),
    "kekerasan_seksual": rng.integers(10,  300, size=len(gdf)),
    "penyakit_menular":  rng.integers(20,  600, size=len(gdf)),
})

# ---------------------------------------------------------------------------
# 2. Build satu peta Folium per layer dengan neon colormap
# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
# 3. Statistik per layer
# ---------------------------------------------------------------------------
stats = {
    key: {
        "total": int(data[key].sum()),
        "avg":   int(data[key].mean()),
        "max":   int(data[key].max()),
        "min":   int(data[key].min()),
        "top":   data.nlargest(5, key)[["id_wilayah", key]].values.tolist(),
    }
    for key in LAYERS
}

maps_json  = json.dumps(maps)
stats_json = json.dumps(stats)
layers_json = json.dumps({k: {"neon": v["neon"]} for k, v in LAYERS.items()})

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
    background: rgba(255,255,0,0.06); border: 1px solid rgba(255,255,0,0.3);
    color: #ffff00; font-size: 0.6rem; letter-spacing: 2px;
    padding: 3px 12px; z-index: 10; pointer-events: none; white-space: nowrap;
  }}
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
    <span>DATA: DUMMY v0.1</span>
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
    <div class="sec" style="color:rgba(255,255,255,0.1)">// TAHUN 2024 · DUMMY DATA</div>
    <div style="font-size:0.58rem;color:rgba(255,255,255,0.15);line-height:1.7;padding:2px 4px">
      Integrasi BPS / Kemenkes / Kemenpppa<br/>sedang dikembangkan.
    </div>
  </aside>

  <div class="map-wrap">
    <div class="c c-tl"></div>
    <div class="c c-tr"></div>
    <div class="c c-bl"></div>
    <div class="c c-br"></div>
    <div class="warn">&#9888; DATA DUMMY — BUKAN DATA RESMI</div>
    <iframe id="map-frame" src="about:blank"></iframe>
    <div class="hud-br">WGS84 · EPSG:4326 · &copy; NEXUS MAP SYS</div>
  </div>
</div>

<script>
const MAPS   = {maps_json};
const STATS  = {stats_json};
const LAYERS = {layers_json};
let blobUrl  = null;

function switchLayer(key, btn) {{
  const neon = LAYERS[key].neon;

  // Update CSS variable global
  document.documentElement.style.setProperty('--neon', neon);

  // Update tombol aktif
  document.querySelectorAll('.layer-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');

  // Update stat values
  const s = STATS[key];
  document.getElementById('s-total').textContent = s.total.toLocaleString('id-ID');
  document.getElementById('s-avg').textContent   = s.avg.toLocaleString('id-ID');
  document.getElementById('s-max').textContent   = s.max.toLocaleString('id-ID');
  document.getElementById('s-min').textContent   = s.min.toLocaleString('id-ID');

  // Update top 5
  document.getElementById('top-body').innerHTML = s.top.map(([w, k], i) =>
    `<tr>
      <td><span class="rank">${{i+1}}.</span></td>
      <td>${{w}}</td>
      <td class="td-val">${{Number(k).toLocaleString('id-ID')}}</td>
    </tr>`
  ).join('');

  // Ganti iframe
  if (blobUrl) URL.revokeObjectURL(blobUrl);
  blobUrl = URL.createObjectURL(new Blob([MAPS[key]], {{type:'text/html'}}));
  document.getElementById('map-frame').src = blobUrl;
}}

// Jam realtime
setInterval(() => {{
  document.getElementById('clk').textContent =
    new Date().toLocaleTimeString('id-ID', {{hour12:false}});
}}, 1000);

// Init layer pertama
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
