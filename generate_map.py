"""
Generate docs/index.html dengan UI cyberpunk dan peta Folium ter-embed.
Usage: python generate_map.py
"""

import sys
import re
from pathlib import Path

import folium
import numpy as np
import pandas as pd
from folium.plugins import MiniMap

sys.path.insert(0, str(Path(__file__).parent / "src"))
from visualize import load_geodataframe, _ID_COLUMNS

DOCS_DIR = Path(__file__).parent / "docs"
DOCS_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# 1. Build Folium map (dark tile, no default controls)
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

def make_folium_map(value_col: str, colormap: str) -> str:
    """Buat peta choropleth dan kembalikan HTML string."""
    import json
    m = folium.Map(
        location=[-2.5, 118.0],
        zoom_start=5,
        tiles=None,
        zoom_control=False,
    )

    # Tile gelap agar sesuai tema cyberpunk
    folium.TileLayer(
        tiles="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
        attr="© OpenStreetMap © CartoDB",
        name="Dark",
        max_zoom=19,
    ).add_to(m)

    merged = gdf.merge(
        data[["id_wilayah", value_col]],
        left_on=id_col, right_on="id_wilayah", how="left",
    )
    geojson_data = json.loads(merged.to_json())

    folium.Choropleth(
        geo_data=geojson_data,
        data=merged,
        columns=[id_col, value_col],
        key_on=f"feature.properties.{id_col}",
        fill_color=colormap,
        fill_opacity=0.65,
        line_opacity=0.4,
        line_color="#00ffff",
        nan_fill_color="#1a1a2e",
        legend_name="",
        highlight=True,
    ).add_to(m)

    folium.GeoJson(
        geojson_data,
        style_function=lambda _: {"fillOpacity": 0, "weight": 0},
        highlight_function=lambda _: {
            "fillColor": "#00ffff",
            "fillOpacity": 0.25,
            "weight": 2,
            "color": "#00ffff",
        },
        tooltip=folium.GeoJsonTooltip(
            fields=[id_col, value_col],
            aliases=["📍 Wilayah", "📊 Kasus"],
            style=(
                "background-color: #0d0d1a;"
                "color: #00ffff;"
                "font-family: 'Share Tech Mono', monospace;"
                "font-size: 13px;"
                "border: 1px solid #00ffff;"
                "box-shadow: 0 0 8px #00ffff55;"
            ),
        ),
    ).add_to(m)

    # Kembalikan hanya konten <body> Folium (tanpa <html><head>)
    html_str = m._repr_html_()
    return html_str

maps = {
    "kriminalitas":      make_folium_map("kriminalitas",      "YlOrRd"),
    "kekerasan_seksual": make_folium_map("kekerasan_seksual", "RdPu"),
    "penyakit_menular":  make_folium_map("penyakit_menular",  "YlGn"),
}

# Statistik per layer untuk ditampilkan di panel
stats = {
    col: {
        "total":    int(data[col].sum()),
        "avg":      int(data[col].mean()),
        "max":      int(data[col].max()),
        "min":      int(data[col].min()),
        "top":      data.nlargest(5, col)[["id_wilayah", col]]
                        .values.tolist(),
    }
    for col in ["kriminalitas", "kekerasan_seksual", "penyakit_menular"]
}

import json
stats_json = json.dumps(stats)
maps_json  = json.dumps(maps)

# ---------------------------------------------------------------------------
# 2. HTML Template Cyberpunk
# ---------------------------------------------------------------------------
HTML = f"""<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>NEXUS // CRIME & HEALTH MAP — INDONESIA</title>
<link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700;900&family=Share+Tech+Mono&display=swap" rel="stylesheet"/>
<style>
  :root {{
    --cyan:    #00ffff;
    --magenta: #ff00ff;
    --green:   #00ff41;
    --yellow:  #ffff00;
    --bg:      #050510;
    --panel:   #0a0a1f;
    --border:  #00ffff33;
  }}

  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

  body {{
    background: var(--bg);
    color: var(--cyan);
    font-family: 'Share Tech Mono', monospace;
    height: 100vh;
    overflow: hidden;
    display: flex;
    flex-direction: column;
  }}

  /* ── Scanline overlay ── */
  body::after {{
    content: '';
    position: fixed;
    inset: 0;
    background: repeating-linear-gradient(
      0deg,
      transparent,
      transparent 2px,
      rgba(0,0,0,0.08) 2px,
      rgba(0,0,0,0.08) 4px
    );
    pointer-events: none;
    z-index: 9999;
  }}

  /* ── Header ── */
  header {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 10px 24px;
    background: var(--panel);
    border-bottom: 1px solid var(--cyan);
    box-shadow: 0 0 20px #00ffff44;
    flex-shrink: 0;
    z-index: 100;
  }}

  .logo {{
    font-family: 'Orbitron', sans-serif;
    font-size: 1.1rem;
    font-weight: 900;
    letter-spacing: 3px;
    text-transform: uppercase;
  }}
  .logo span {{ color: var(--magenta); }}

  .header-right {{
    display: flex;
    align-items: center;
    gap: 24px;
    font-size: 0.75rem;
    letter-spacing: 1px;
    color: #ffffff88;
  }}
  .header-right .dot {{
    width: 8px; height: 8px;
    border-radius: 50%;
    background: var(--green);
    box-shadow: 0 0 8px var(--green);
    animation: blink 1.5s infinite;
    display: inline-block;
    margin-right: 6px;
  }}
  @keyframes blink {{ 0%,100% {{ opacity:1 }} 50% {{ opacity:0.2 }} }}

  /* ── Main layout ── */
  .main {{
    display: flex;
    flex: 1;
    overflow: hidden;
  }}

  /* ── Sidebar ── */
  aside {{
    width: 260px;
    flex-shrink: 0;
    background: var(--panel);
    border-right: 1px solid var(--border);
    display: flex;
    flex-direction: column;
    gap: 0;
    overflow-y: auto;
    padding: 16px 12px;
  }}

  .section-title {{
    font-family: 'Orbitron', sans-serif;
    font-size: 0.6rem;
    letter-spacing: 3px;
    color: #ffffff55;
    text-transform: uppercase;
    margin-bottom: 8px;
    padding-left: 4px;
  }}

  /* ── Layer buttons ── */
  .layer-btn {{
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px 12px;
    margin-bottom: 6px;
    background: transparent;
    border: 1px solid #00ffff22;
    color: #ffffff88;
    font-family: 'Share Tech Mono', monospace;
    font-size: 0.78rem;
    letter-spacing: 1px;
    cursor: pointer;
    text-align: left;
    transition: all 0.2s;
    position: relative;
    overflow: hidden;
  }}
  .layer-btn::before {{
    content: '';
    position: absolute;
    left: 0; top: 0; bottom: 0;
    width: 3px;
    background: var(--accent-color, var(--cyan));
    box-shadow: 0 0 8px var(--accent-color, var(--cyan));
  }}
  .layer-btn:hover, .layer-btn.active {{
    border-color: var(--accent-color, var(--cyan));
    color: var(--accent-color, var(--cyan));
    background: rgba(0,255,255,0.05);
    box-shadow: 0 0 12px var(--accent-color, var(--cyan))22;
  }}
  .layer-btn .icon {{ font-size: 1.1rem; }}

  /* ── Stats panel ── */
  .stats-grid {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
    margin-bottom: 12px;
  }}
  .stat-card {{
    background: #0d0d2a;
    border: 1px solid var(--border);
    padding: 10px 8px;
    text-align: center;
  }}
  .stat-label {{
    font-size: 0.6rem;
    letter-spacing: 2px;
    color: #ffffff44;
    text-transform: uppercase;
    margin-bottom: 4px;
  }}
  .stat-value {{
    font-family: 'Orbitron', sans-serif;
    font-size: 1rem;
    font-weight: 700;
    color: var(--active-color, var(--cyan));
    text-shadow: 0 0 10px var(--active-color, var(--cyan));
  }}

  /* ── Top 5 table ── */
  .top-table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 0.72rem;
    margin-bottom: 8px;
  }}
  .top-table thead th {{
    color: #ffffff44;
    letter-spacing: 2px;
    font-size: 0.6rem;
    text-transform: uppercase;
    padding: 4px 6px;
    border-bottom: 1px solid var(--border);
  }}
  .top-table tbody tr {{ transition: background 0.15s; }}
  .top-table tbody tr:hover {{ background: rgba(0,255,255,0.05); }}
  .top-table td {{
    padding: 5px 6px;
    border-bottom: 1px solid #ffffff08;
    color: #ffffffbb;
  }}
  .top-table td:last-child {{
    color: var(--active-color, var(--cyan));
    text-align: right;
    font-family: 'Orbitron', sans-serif;
    font-size: 0.7rem;
  }}
  .rank {{ color: #ffffff33; margin-right: 4px; }}

  /* ── Divider ── */
  .divider {{
    border: none;
    border-top: 1px solid var(--border);
    margin: 14px 0;
  }}

  /* ── Map area ── */
  .map-container {{
    flex: 1;
    position: relative;
    display: flex;
    flex-direction: column;
  }}

  .map-frame {{
    flex: 1;
    border: none;
    display: block;
  }}

  /* ── Corner decorations ── */
  .corner {{
    position: absolute;
    width: 20px; height: 20px;
    z-index: 10;
    pointer-events: none;
  }}
  .corner-tl {{ top: 8px; left: 8px; border-top: 2px solid var(--cyan); border-left: 2px solid var(--cyan); box-shadow: -2px -2px 6px var(--cyan)44; }}
  .corner-tr {{ top: 8px; right: 8px; border-top: 2px solid var(--cyan); border-right: 2px solid var(--cyan); box-shadow: 2px -2px 6px var(--cyan)44; }}
  .corner-bl {{ bottom: 8px; left: 8px; border-bottom: 2px solid var(--cyan); border-left: 2px solid var(--cyan); box-shadow: -2px 2px 6px var(--cyan)44; }}
  .corner-br {{ bottom: 8px; right: 8px; border-bottom: 2px solid var(--cyan); border-right: 2px solid var(--cyan); box-shadow: 2px 2px 6px var(--cyan)44; }}

  /* ── HUD overlay ── */
  .hud-overlay {{
    position: absolute;
    bottom: 20px;
    right: 20px;
    background: #0a0a1fcc;
    border: 1px solid var(--border);
    padding: 8px 14px;
    font-size: 0.65rem;
    letter-spacing: 2px;
    color: #ffffff44;
    z-index: 10;
    backdrop-filter: blur(4px);
    pointer-events: none;
  }}

  /* ── Warning badge ── */
  .warn-badge {{
    position: absolute;
    top: 14px;
    left: 50%;
    transform: translateX(-50%);
    background: #ffff0011;
    border: 1px solid #ffff0044;
    color: var(--yellow);
    font-size: 0.62rem;
    letter-spacing: 2px;
    padding: 4px 14px;
    z-index: 10;
    pointer-events: none;
    white-space: nowrap;
  }}

  /* ── Scrollbar ── */
  aside::-webkit-scrollbar {{ width: 4px; }}
  aside::-webkit-scrollbar-track {{ background: transparent; }}
  aside::-webkit-scrollbar-thumb {{ background: #00ffff33; border-radius: 2px; }}
</style>
</head>
<body>

<!-- ══ HEADER ══════════════════════════════════════════════════════════════ -->
<header>
  <div class="logo">NEXUS<span>//</span>MAP <span style="color:#ffffff33;font-size:0.7rem;margin-left:8px;">INDONESIA CRIME & HEALTH</span></div>
  <div class="header-right">
    <span><span class="dot"></span>SYSTEM ONLINE</span>
    <span>DATA: DUMMY v0.1</span>
    <span id="clock">--:--:--</span>
  </div>
</header>

<!-- ══ MAIN ════════════════════════════════════════════════════════════════ -->
<div class="main">

  <!-- ── SIDEBAR ─────────────────────────────────────────────────────────── -->
  <aside>
    <div class="section-title">// DATA LAYER</div>

    <button class="layer-btn active"
      style="--accent-color:#ff6b35"
      onclick="switchLayer('kriminalitas', '#ff6b35', this)">
      <span class="icon">⚠</span> KRIMINALITAS UMUM
    </button>
    <button class="layer-btn"
      style="--accent-color:#ff00ff"
      onclick="switchLayer('kekerasan_seksual', '#ff00ff', this)">
      <span class="icon">🛡</span> KEKERASAN SEKSUAL
    </button>
    <button class="layer-btn"
      style="--accent-color:#00ff41"
      onclick="switchLayer('penyakit_menular', '#00ff41', this)">
      <span class="icon">⚕</span> PENYAKIT MENULAR
    </button>

    <hr class="divider"/>
    <div class="section-title">// STATISTIK NASIONAL</div>

    <div class="stats-grid" id="stats-grid">
      <div class="stat-card">
        <div class="stat-label">TOTAL</div>
        <div class="stat-value" id="stat-total">—</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">RATA-RATA</div>
        <div class="stat-value" id="stat-avg">—</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">TERTINGGI</div>
        <div class="stat-value" id="stat-max">—</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">TERENDAH</div>
        <div class="stat-value" id="stat-min">—</div>
      </div>
    </div>

    <hr class="divider"/>
    <div class="section-title">// TOP 5 WILAYAH</div>

    <table class="top-table">
      <thead>
        <tr><th>#</th><th>WILAYAH</th><th>KASUS</th></tr>
      </thead>
      <tbody id="top-tbody"></tbody>
    </table>

    <hr class="divider"/>
    <div class="section-title" style="color:#ffffff22">// TAHUN: 2024 (DUMMY)</div>
    <div style="font-size:0.6rem;color:#ffffff22;line-height:1.6;padding:4px">
      Sumber: Data simulasi.<br/>
      Integrasi BPS / Kemenkes<br/>
      sedang dikembangkan.
    </div>
  </aside>

  <!-- ── MAP ──────────────────────────────────────────────────────────────── -->
  <div class="map-container">
    <div class="corner corner-tl"></div>
    <div class="corner corner-tr"></div>
    <div class="corner corner-bl"></div>
    <div class="corner corner-br"></div>
    <div class="warn-badge">⚠ DATA DUMMY — BUKAN DATA RESMI</div>
    <iframe id="map-frame" class="map-frame" src="about:blank"></iframe>
    <div class="hud-overlay">© NEXUS MAP SYS · WGS84 · EPSG:4326</div>
  </div>

</div>

<!-- ══ SCRIPT ══════════════════════════════════════════════════════════════ -->
<script>
const MAPS  = {maps_json};
const STATS = {stats_json};
let activeColor = '#ff6b35';

function switchLayer(key, color, btn) {{
  activeColor = color;

  // Update tombol aktif
  document.querySelectorAll('.layer-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');

  // Update warna stat cards
  document.querySelectorAll('.stat-value').forEach(el => {{
    el.style.color = color;
    el.style.textShadow = `0 0 10px ${{color}}`;
  }});

  // Update stats
  const s = STATS[key];
  document.getElementById('stat-total').textContent = s.total.toLocaleString('id-ID');
  document.getElementById('stat-avg').textContent   = s.avg.toLocaleString('id-ID');
  document.getElementById('stat-max').textContent   = s.max.toLocaleString('id-ID');
  document.getElementById('stat-min').textContent   = s.min.toLocaleString('id-ID');

  // Update top 5
  const tbody = document.getElementById('top-tbody');
  tbody.innerHTML = s.top.map(([wilayah, kasus], i) => `
    <tr>
      <td><span class="rank">${{i+1}}.</span></td>
      <td>${{wilayah}}</td>
      <td style="color:${{color}}">${{kasus.toLocaleString('id-ID')}}</td>
    </tr>
  `).join('');

  // Ganti iframe map
  const frame = document.getElementById('map-frame');
  const blob  = new Blob([MAPS[key]], {{type: 'text/html'}});
  const url   = URL.createObjectURL(blob);
  frame.src   = url;
}}

// Jam realtime
function updateClock() {{
  const now = new Date();
  document.getElementById('clock').textContent =
    now.toLocaleTimeString('id-ID', {{hour12: false}});
}}
setInterval(updateClock, 1000);
updateClock();

// Init layer pertama
document.addEventListener('DOMContentLoaded', () => {{
  switchLayer('kriminalitas', '#ff6b35', document.querySelector('.layer-btn'));
}});
</script>
</body>
</html>"""

out = DOCS_DIR / "index.html"
out.write_text(HTML, encoding="utf-8")
print(f"OK Peta cyberpunk disimpan di {out}")
print("Jalankan: git add docs/index.html && git push")
