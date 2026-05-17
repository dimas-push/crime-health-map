"""
Generate docs/index.html + docs/maps/*.html dengan UI cyberpunk dan peta Folium.
Usage: python generate_map.py
"""

import json
import sqlite3
import sys
from pathlib import Path

import math

import branca.colormap as cm
import folium
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent / "src"))
from collect_news import collect_news
from collect_official import collect_all as collect_official_all
from collect_social import collect_social
from process import process_all
from sentiment import run_sentiment_analysis
from visualize import _ID_COLUMNS, load_geodataframe

DOCS_DIR      = Path(__file__).parent / "docs"
MAPS_DIR      = DOCS_DIR / "maps"
PROCESSED_DIR = Path(__file__).parent / "data" / "processed"
DB_PATH       = PROCESSED_DIR / "crime_health.db"
DOCS_DIR.mkdir(exist_ok=True)
MAPS_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------
def load_or_build_data() -> pd.DataFrame:
    final_csv = PROCESSED_DIR / "final.csv"
    if final_csv.exists():
        print("[generate_map] Memuat data dari cache (final.csv) ...")
        return pd.read_csv(final_csv)
    print("[generate_map] Data belum ada, jalankan pipeline ...")
    collect_official_all()
    collect_news()
    collect_social()
    df = process_all()
    run_sentiment_analysis(use_model=False)
    return df


def load_crime_detail() -> pd.DataFrame:
    if not DB_PATH.exists():
        return pd.DataFrame()
    with sqlite3.connect(DB_PATH) as conn:
        try:
            # Kolom bisa bernama 'jumlah' atau 'jumlah_kasus' tergantung pipeline
            cols = [r[1] for r in conn.execute(
                "PRAGMA table_info(kriminalitas_detail)"
            ).fetchall()]
            val_col = "jumlah_kasus" if "jumlah_kasus" in cols else "jumlah"
            return pd.read_sql(
                f"SELECT nama_provinsi, jenis_kejahatan, {val_col} as jumlah_kasus "
                "FROM kriminalitas_detail",
                conn,
            )
        except Exception:
            return pd.DataFrame()


def load_articles() -> pd.DataFrame:
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
            result: dict = {}
            for kat, grp in df.groupby("kategori"):
                result[kat] = grp.set_index("sentimen")["jumlah"].to_dict()
            return result
        except Exception:
            return {}


# ---------------------------------------------------------------------------
# Konfigurasi layer
# ---------------------------------------------------------------------------
LAYERS = {
    "kriminalitas": {
        "label":  "KRIMINALITAS UMUM",
        "icon":   "&#9888;",
        "neon":   "#ff6b35",
        "colors": ["#0d0015", "#3d0020", "#8b0000", "#cc3300", "#ff6b35"],
        "col":    "jumlah_kasus",
    },
    "kekerasan_seksual": {
        "label":  "KEKERASAN SEKSUAL",
        "icon":   "&#128737;",
        "neon":   "#ff00ff",
        "colors": ["#0d001a", "#2d0040", "#7700aa", "#cc00cc", "#ff00ff"],
        "col":    "jumlah_kasus",
    },
    "penyakit_menular": {
        "label":  "PENYAKIT MENULAR",
        "icon":   "&#9877;",
        "neon":   "#00ff41",
        "colors": ["#001a0d", "#003320", "#006600", "#00bb33", "#00ff41"],
        "col":    "jumlah_kasus",
    },
}

CRIME_TYPES = {
    "pencurian":      {"label": "PENCURIAN",      "neon": "#ff9900"},
    "narkoba":        {"label": "NARKOBA",         "neon": "#ff6b35"},
    "penipuan":       {"label": "PENIPUAN",        "neon": "#ffcc00"},
    "penganiayaan":   {"label": "PENGANIAYAAN",    "neon": "#ff4444"},
    "pembunuhan":     {"label": "PEMBUNUHAN",      "neon": "#cc0000"},
    "korupsi":        {"label": "KORUPSI",         "neon": "#ff8800"},
    "begal_curanmor": {"label": "BEGAL/CURANMOR", "neon": "#ff5500"},
}


# ---------------------------------------------------------------------------
# 1. Load semua data
# ---------------------------------------------------------------------------
print("Memuat GeoDataFrame provinsi ...")
gdf    = load_geodataframe("provinsi")
id_col = _ID_COLUMNS["provinsi"]

df_final         = load_or_build_data()
sentimen_summary = load_sentiment_summary()
df_articles      = load_articles()
df_crime_detail  = load_crime_detail()

# Load sentimen per artikel
def _load_sentiment_df() -> pd.DataFrame:
    if not DB_PATH.exists():
        return pd.DataFrame()
    with sqlite3.connect(DB_PATH) as conn:
        try:
            return pd.read_sql(
                "SELECT tweet_id, sentimen, sentimen_score FROM data_sentimen", conn
            )
        except Exception:
            return pd.DataFrame()

df_sentiment = _load_sentiment_df()
IS_DUMMY = not (PROCESSED_DIR / "final.csv").exists()

# Load dataset tambahan
RAW_DIR = Path(__file__).parent / "data" / "raw"

def _load_extra_csv(filename: str, val_col: str, prov_col: str = "nama_provinsi") -> pd.Series:
    path = RAW_DIR / filename
    if not path.exists():
        return pd.Series(dtype=float)
    df = pd.read_csv(path)
    if val_col not in df.columns or prov_col not in df.columns:
        return pd.Series(dtype=float)
    return df.set_index(prov_col)[val_col]

# Populasi per provinsi 2023 (BPS Proyeksi Penduduk)
_POPULASI = {
    "Aceh": 5481118, "Sumatera Utara": 15114918, "Sumatera Barat": 5621197,
    "Riau": 6816653, "Jambi": 3641504, "Sumatera Selatan": 8786072,
    "Bengkulu": 2049422, "Lampung": 9127033, "Kepulauan Bangka Belitung": 1478674,
    "Kepulauan Riau": 2219100, "DKI Jakarta": 10562088, "Jawa Barat": 49935858,
    "Jawa Tengah": 36741420, "DI Yogyakarta": 3847734, "Jawa Timur": 40665696,
    "Banten": 13028566, "Bali": 4422764, "Nusa Tenggara Barat": 5296008,
    "Nusa Tenggara Timur": 5629584, "Kalimantan Barat": 5574368,
    "Kalimantan Tengah": 2718003, "Kalimantan Selatan": 4362556,
    "Kalimantan Timur": 4004793, "Kalimantan Utara": 760579,
    "Sulawesi Utara": 2629755, "Sulawesi Tengah": 3151369,
    "Sulawesi Selatan": 9434183, "Sulawesi Tenggara": 2758054,
    "Gorontalo": 1192717, "Sulawesi Barat": 1413069,
    "Maluku": 1848923, "Maluku Utara": 1319022,
    "Papua Barat": 1148855, "Papua": 4356700,
}
_pop_series = pd.Series(_POPULASI)

# Pivot data per kategori (3 kategori utama dari df_final, 2 dari CSV terpisah)
def _pivot(df: pd.DataFrame, kategori: str) -> pd.Series:
    return (
        df[df["kategori"] == kategori]
        .groupby("nama_provinsi")["jumlah_kasus"]
        .sum()
    )

data = pd.DataFrame({"id_wilayah": gdf[id_col]})
for kat in LAYERS:
    data[kat] = data["id_wilayah"].map(_pivot(df_final, kat)).fillna(0).astype(int)

# Per-kapita: kasus per 100k penduduk
_crime_rate_raw = _load_extra_csv("kriminalitas_rate.csv", "crime_rate_per_100k")
def _per100k(series: pd.Series, use_raw: pd.Series | None = None) -> pd.Series:
    if use_raw is not None and not use_raw.empty:
        return use_raw.reindex(series.index).fillna(0)
    pop = _pop_series.reindex(series.index).replace(0, pd.NA)
    return (series / pop * 100000).fillna(0).round(1)

def _to_prov_series(series_or_df_col: pd.Series) -> pd.Series:
    """Deduplicate index by grouping (sum) to ensure unique province index."""
    s = series_or_df_col.copy()
    if s.index.duplicated().any():
        s = s.groupby(s.index).sum()
    return s

_data_idx = data.set_index("id_wilayah")
_per100k_data = {
    "kriminalitas":     _per100k(_to_prov_series(_data_idx["kriminalitas"]), _crime_rate_raw),
    "kekerasan_seksual":_per100k(_to_prov_series(_data_idx["kekerasan_seksual"])),
    "penyakit_menular": _per100k(_to_prov_series(_data_idx["penyakit_menular"])),
}

# Risk score: composite index 0-100 dari semua kategori (min-max normalisasi)
def _risk_score() -> pd.Series:
    from process import PROVINSI_RESMI
    scores = pd.Series(0.0, index=PROVINSI_RESMI)
    count  = pd.Series(0,   index=PROVINSI_RESMI)
    for kat, s in _per100k_data.items():
        mx = s.max()
        if mx <= 0:
            continue
        norm = (s / mx).reindex(PROVINSI_RESMI).fillna(0)
        scores += norm
        count  += (norm > 0).astype(int)
    combined = scores / count.replace(0, 1)
    mx = combined.max()
    if mx > 0:
        combined = (combined / mx * 100).round(1)
    return combined

_risk_scores = _risk_score()

# Statistik artikel berita per layer
def _news_stats(kategori: str) -> dict:
    if df_articles.empty:
        return {"total": 0, "top": [], "per_prov": {}}
    sub = df_articles[df_articles["kategori"] == kategori]
    per_prov = (
        sub.groupby("provinsi").size().reset_index(name="jumlah")
        if "provinsi" in sub.columns else pd.DataFrame()
    )
    top5 = (
        per_prov.nlargest(5, "jumlah")[["provinsi", "jumlah"]].values.tolist()
        if not per_prov.empty else []
    )
    return {
        "total":    int(len(sub)),
        "top":      [[str(r[0]), int(r[1])] for r in top5],
        "per_prov": per_prov.set_index("provinsi")["jumlah"].to_dict()
                    if not per_prov.empty else {},
    }

news_stats = {k: _news_stats(k) for k in LAYERS}

# Statistik crime type detail
crime_type_stats: dict = {}
for jenis, cfg in CRIME_TYPES.items():
    if df_crime_detail.empty:
        crime_type_stats[jenis] = {"total": 0, "avg": 0, "max": 0, "min": 0, "top": [],
                                   "neon": cfg["neon"], "label": cfg["label"]}
        continue
    pivot = (
        df_crime_detail[df_crime_detail["jenis_kejahatan"] == jenis]
        .groupby("nama_provinsi")["jumlah_kasus"].sum()
    )
    col_data = gdf[id_col].map(pivot).fillna(0).astype(int)
    top5 = (
        df_crime_detail[df_crime_detail["jenis_kejahatan"] == jenis]
        .groupby("nama_provinsi")["jumlah_kasus"].sum()
        .nlargest(5).reset_index().values.tolist()
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

# Statistik per layer utama
def _stats_for(key: str) -> dict:
    s = data[key]
    p = _per100k_data.get(key, pd.Series(dtype=float))
    top5 = data.nlargest(5, key)[["id_wilayah", key]].values.tolist()
    top5_p = (
        p.nlargest(5).reset_index().values.tolist()
        if not p.empty else []
    )
    return {
        "total":      int(s.sum()),
        "avg":        int(s.mean()),
        "max":        int(s.max()),
        "min":        int(s.min()),
        "top":        top5,
        "per100k_avg": float(round(p.mean(), 1)) if not p.empty else 0,
        "per100k_max": float(round(p.max(), 1)) if not p.empty else 0,
        "top_per100k": [[str(r[0]), float(r[1])] for r in top5_p],
        "markers":    int(len(df_articles[df_articles["kategori"] == key]))
                      if not df_articles.empty else 0,
    }

stats = {key: _stats_for(key) for key in LAYERS}

# Risk score per provinsi (untuk sidebar)
_risk_top10 = (
    _risk_scores.nlargest(10).reset_index().values.tolist()
    if not _risk_scores.empty else []
)


# ---------------------------------------------------------------------------
# 2. Map generation — setiap layer disimpan sebagai file HTML terpisah
# ---------------------------------------------------------------------------
def _articles_for(kategori: str) -> list[dict]:
    """Kembalikan daftar artikel untuk kategori tertentu sebagai list of dict."""
    if df_articles.empty:
        return []
    cols = ["judul", "deskripsi", "url", "tanggal", "sumber",
            "kategori", "provinsi", "kabupaten", "lat", "lon"]
    sub = df_articles[df_articles["kategori"] == kategori].copy()
    # Merge sentimen jika ada
    if not df_sentiment.empty and "tweet_id" in df_sentiment.columns:
        # Gunakan index integer artikel sebagai tweet_id proxy
        sub = sub.reset_index()
        df_sent_str = df_sentiment.copy()
        df_sent_str["tweet_id"] = df_sent_str["tweet_id"].astype(str)
        sub["idx_str"] = sub["index"].astype(str)
        sub = sub.merge(
            df_sent_str[["tweet_id", "sentimen", "sentimen_score"]],
            left_on="idx_str", right_on="tweet_id", how="left"
        ).drop(columns=["index", "idx_str", "tweet_id"], errors="ignore")
    existing = [c for c in cols + ["sentimen"] if c in sub.columns]
    return sub[existing].fillna("").to_dict(orient="records")


def _inject_markers(html: str, articles: list[dict], neon: str,
                    colors: list[str] | None = None,
                    vmin: float = 0, vmax: float = 100,
                    label: str = "Kasus") -> str:
    """
    Inject script marker + legend ke dalam Folium HTML standalone.
    Script menerima postMessage {days: N} dari parent untuk filter waktu.
    """
    arts_json = json.dumps(articles, ensure_ascii=False).replace('</', r'<\/')

    # Script dibangun sebagai string concatenation, bukan f-string,
    # agar tidak ada konflik {{ }} antara JS dan Python.
    script = (
        '(function(){'
        'var NEON="' + neon + '";'
        'var ARTS=' + arts_json + ';'
        'var _layer=null;'

        'function esc(s){'
        's=String(s||"");'
        's=s.replace(/&/g,"&amp;");'
        's=s.replace(/[<]/g,"&lt;");'
        's=s.replace(/[>]/g,"&gt;");'
        's=s.replace(/"/g,"&quot;");'
        "s=s.replace(/'/g,\"&#39;\");"
        'return s;}'

        'function _getMap(){'
        'var ks=Object.keys(window);'
        'for(var i=0;i<ks.length;i++){'
        'try{var v=window[ks[i]];'
        'if(v&&v._leaflet_id!=null&&typeof v.addLayer==="function")return v;'
        '}catch(e){}}'
        'return null;}'

        'function buildMarkers(days){'
        'var m=_getMap();'
        'if(!m){setTimeout(function(){buildMarkers(days);},200);return;}'
        'if(_layer){m.removeLayer(_layer);}'
        '_layer=L.layerGroup().addTo(m);'
        'var cutoff=days>0?new Date(Date.now()-days*86400000):null;'
        'var count=0;'
        'ARTS.forEach(function(a){'
        'if(!a.lat||!a.lon)return;'
        'if(cutoff){var d=new Date(a.tanggal);if(!isNaN(d)&&d<cutoff)return;}'
        'count++;'
        'var mk=L.circleMarker([a.lat,a.lon],'
        '{radius:7,color:NEON,fillColor:NEON,fillOpacity:0.85,weight:2});'
        'var jd=esc(String(a.judul||"").slice(0,120));'
        'var ds=esc(String(a.deskripsi||"").slice(0,200));'
        'var tg=esc(String(a.tanggal||"").slice(0,16));'
        'var sr=esc(String(a.sumber||""));'
        'var kb=esc(String(a.kabupaten||""));'
        'var ur=String(a.url||"#");'
        'var mt=tg+(sr?" | "+sr:"")+(kb?" | "+kb:"");'
        'var pop='
        '"<div style=\'background:#0a0a1f;color:"+NEON+";font-family:monospace;font-size:12px;'
        'border:1px solid "+NEON+";padding:10px;max-width:280px;box-shadow:0 0 12px "+NEON+"55;\'>"'
        '+"<div style=\'font-weight:bold;font-size:13px;margin-bottom:6px;color:#fff;'
        'border-bottom:1px solid "+NEON+"44;padding-bottom:4px;\'>"+jd+"</div>"'
        '+"<div style=\'color:"+NEON+"99;font-size:11px;margin-bottom:6px;\'>"+ds+"</div>"'
        '+"<div style=\'font-size:10px;color:"+NEON+"66;margin-bottom:8px;\'>"+mt+"</div>"'
        '+"<a href=\'"+ur+"\' target=\'_blank\' style=\'color:"+NEON+";text-decoration:none;'
        'font-size:11px;border:1px solid "+NEON+";padding:2px 8px;\'>BACA &#8594;</a></div>";'
        'mk.bindPopup(pop,{maxWidth:300});'
        'mk.bindTooltip(esc(String(a.judul||"").slice(0,60)));'
        '_layer.addLayer(mk);});'
        # Beritahu parent jumlah marker
        "try{window.parent.postMessage({type:'markerCount',count:count},'*');}catch(e){}"
        '}'

        # Attach click handler ke GeoJSON layer untuk kirim data provinsi ke parent
        'function _attachProvinsiClick(){'
        'var m=_getMap();'
        'if(!m){setTimeout(_attachProvinsiClick,300);return;}'
        'try{'
        'm.eachLayer(function(layer){'
        'if(layer.eachLayer){layer.eachLayer(function(sub){'
        'if(sub.feature){sub.on("click",function(e){'
        'var p=e.target.feature.properties||{};'
        'var prov=p.PROVINSI||p.WADMPR||p.NAME_1||p.name||"";'
        'var arts=ARTS.filter(function(a){return a.provinsi&&a.provinsi===prov;});'
        "try{window.parent.postMessage({type:'provinsiClick',provinsi:prov,articles:arts},'*');}catch(ex){}"
        '});}'
        '});}'
        '});'
        '}catch(ex){}}'
        '_attachProvinsiClick();'

        'window.addEventListener("message",function(e){'
        'if(e.data&&typeof e.data.days==="number")buildMarkers(e.data.days);});'

        'document.addEventListener("DOMContentLoaded",function(){buildMarkers(0);});'
        '})();'
    )

    # Legend HTML
    if colors:
        grad = ', '.join(colors)
        legend_html = (
            f'<div style="position:fixed;bottom:28px;right:12px;z-index:9999;'
            f'background:rgba(8,8,26,0.88);border:1px solid {neon};padding:8px 12px;'
            f'font-family:monospace;font-size:11px;color:{neon};backdrop-filter:blur(4px);">'
            f'<div style="margin-bottom:4px;letter-spacing:2px;font-size:10px;'
            f'color:rgba(255,255,255,0.4);">{label.upper()}</div>'
            f'<div style="display:flex;align-items:center;gap:6px;">'
            f'<span style="font-size:10px;color:rgba(255,255,255,0.35);">'
            f'{int(vmin):,}</span>'
            f'<div style="width:80px;height:8px;background:linear-gradient(to right,{grad});'
            f'border-radius:2px;"></div>'
            f'<span style="font-size:10px;color:rgba(255,255,255,0.35);">'
            f'{int(vmax):,}</span>'
            f'</div></div>'
        )
    else:
        legend_html = ''

    tag = '<scr' + 'ipt>' + script + '</' + 'scr' + 'ipt>'
    return html.replace('</body>', legend_html + tag + '</body>', 1)


def _make_folium_map(neon: str, geojson_data: dict, value_col: str,
                     colormap: cm.LinearColormap,
                     tooltip_alias: str = "Kasus",
                     extra_fields: list | None = None,
                     extra_aliases: list | None = None,
                     log_scale: bool = False) -> folium.Map:
    """Buat Folium Map dengan choropleth dan tooltip."""
    m = folium.Map(location=[-2.5, 118.0], zoom_start=5, tiles=None, zoom_control=False)
    folium.TileLayer(
        tiles="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
        attr="© CartoDB", max_zoom=19,
    ).add_to(m)
    fields  = [id_col, value_col] + (extra_fields or [])
    aliases = ["Wilayah", tooltip_alias] + (extra_aliases or [])
    if log_scale:
        def _style(feat, _cm=colormap, _col=value_col):
            v = feat["properties"].get(_col) or 0
            return {
                "fillColor":   _cm(math.log1p(v)),
                "fillOpacity": 0.75,
                "color":       "#0a0a1f",
                "weight":      0.8,
            }
    else:
        def _style(feat, _cm=colormap, _col=value_col):
            return {
                "fillColor":   _cm(feat["properties"].get(_col) or 0),
                "fillOpacity": 0.75,
                "color":       "#0a0a1f",
                "weight":      0.8,
            }
    folium.GeoJson(
        geojson_data,
        style_function=_style,
        highlight_function=lambda _, n=neon: {
            "fillColor": n, "fillOpacity": 0.35,
            "color": n, "weight": 2,
        },
        tooltip=folium.GeoJsonTooltip(
            fields=fields,
            aliases=aliases,
            style=(
                f"background:#0a0a1f;color:{neon};"
                f"font-family:'Share Tech Mono',monospace;font-size:12px;"
                f"border:1px solid {neon};box-shadow:0 0 8px {neon}88;border-radius:0;"
            ),
        ),
    ).add_to(m)
    return m


_TOOLTIP_ALIAS = {
    "kriminalitas":     "Kasus",
    "kekerasan_seksual":"Kasus",
    "penyakit_menular": "Kasus",

}


_LOG_SCALE_LAYERS = {"penyakit_menular"}


def make_map(key: str) -> None:
    """Buat peta choropleth per layer utama, simpan ke docs/maps/{key}.html."""
    import json as _json
    cfg    = LAYERS[key]
    neon   = cfg["neon"]
    values = data[key]
    use_log = key in _LOG_SCALE_LAYERS
    if use_log:
        vmin = math.log1p(float(values.min()))
        vmax = math.log1p(float(max(values.max(), 1)))
    else:
        vmin = float(values.min())
        vmax = float(max(values.max(), 1))
    colormap = cm.LinearColormap(colors=cfg["colors"], vmin=vmin, vmax=vmax)
    # Merge nilai absolut + per-kapita ke GeoJSON properties
    merged = gdf.merge(data[["id_wilayah", key]], left_on=id_col, right_on="id_wilayah", how="left")
    p100k_col = key + "_per100k"
    p100k_series = _per100k_data.get(key, pd.Series(dtype=float))
    merged[p100k_col] = merged[id_col].map(p100k_series).fillna(0).round(1)
    geojson_data = _json.loads(merged.to_json())

    tip = _TOOLTIP_ALIAS.get(key, "Kasus")

    # Buat Folium map dengan tooltip yang menampilkan keduanya
    m = _make_folium_map(neon, geojson_data, key, colormap,
                         tooltip_alias=tip,
                         extra_fields=[p100k_col],
                         extra_aliases=["Per 100rb Jiwa"],
                         log_scale=use_log)

    html = m.get_root().render()
    html = _inject_markers(html, _articles_for(key), neon,
                           colors=cfg["colors"],
                           vmin=float(values.min()), vmax=float(max(values.max(), 1)),
                           label=tip)
    (MAPS_DIR / f"{key}.html").write_text(html, encoding="utf-8")
    print(f"  [map] {key}.html disimpan ({len(html)//1024} KB)")


def make_crime_type_map(jenis: str) -> None:
    """Buat peta choropleth per jenis kejahatan, simpan ke docs/maps/crime_{jenis}.html."""
    cfg  = CRIME_TYPES[jenis]
    neon = cfg["neon"]

    dest = MAPS_DIR / f"crime_{jenis}.html"

    if df_crime_detail.empty:
        # Fallback: salin peta kriminalitas utama
        src = MAPS_DIR / "kriminalitas.html"
        if src.exists():
            dest.write_bytes(src.read_bytes())
        print(f"  [map] crime_{jenis}.html (fallback dari kriminalitas)")
        return

    pivot = (
        df_crime_detail[df_crime_detail["jenis_kejahatan"] == jenis]
        .groupby("nama_provinsi")["jumlah_kasus"].sum()
    )
    col_data = pd.DataFrame({"id_wilayah": gdf[id_col]})
    col_data[jenis] = col_data["id_wilayah"].map(pivot).fillna(0).astype(int)

    colormap = cm.LinearColormap(
        colors=["#0a0a1f", "#1a0800", "#551500", "#aa3300", neon],
        vmin=col_data[jenis].min(),
        vmax=max(col_data[jenis].max(), 1),
    )

    import json as _json
    merged = gdf.merge(col_data, left_on=id_col, right_on="id_wilayah", how="left")
    geojson_data = _json.loads(merged.to_json())

    m = _make_folium_map(neon, geojson_data, jenis, colormap, tooltip_alias="Kasus")
    html = m.get_root().render()
    crime_colors = ["#0a0a1f", "#1a0800", "#551500", "#aa3300", neon]
    html = _inject_markers(html, [], neon,
                           colors=crime_colors,
                           vmin=float(col_data[jenis].min()),
                           vmax=float(max(col_data[jenis].max(), 1)),
                           label=cfg["label"])
    dest.write_text(html, encoding="utf-8")
    print(f"  [map] crime_{jenis}.html disimpan ({len(html)//1024} KB)")


# ---------------------------------------------------------------------------
# 3. Generate semua file peta
# ---------------------------------------------------------------------------
print("\nMembuat peta per layer ...")
for key in LAYERS:
    make_map(key)

print("\nMembuat peta per jenis kejahatan ...")
for jenis in CRIME_TYPES:
    make_crime_type_map(jenis)


# ---------------------------------------------------------------------------
# 4. Data JSON untuk index.html (kecil, tanpa HTML peta)
# ---------------------------------------------------------------------------
crime_type_stats_json = json.dumps(crime_type_stats)
stats_json            = json.dumps(stats)
news_stats_json       = json.dumps(news_stats)
layers_json           = json.dumps({k: {"neon": v["neon"], "label": v["label"]} for k, v in LAYERS.items()})
sentimen_json         = json.dumps(sentimen_summary)
risk_json             = json.dumps([[str(r[0]), float(r[1])] for r in _risk_top10])

# Serialize semua artikel untuk marker-count update dari parent
def _articles_to_json() -> str:
    if df_articles.empty:
        return "[]"
    cols = ["judul", "tanggal", "kategori", "lat", "lon"]
    existing = [c for c in cols if c in df_articles.columns]
    return df_articles[existing].to_json(orient="records", force_ascii=False)

articles_json = _articles_to_json()


def _build_weekly_trend() -> str:
    """Hitung jumlah artikel per minggu per kategori (12 minggu terakhir)."""
    if df_articles.empty or "tanggal" not in df_articles.columns:
        return "{}"
    df = df_articles.copy()
    df["tanggal"] = pd.to_datetime(df["tanggal"], errors="coerce")
    df = df.dropna(subset=["tanggal", "kategori"])
    df["week"] = df["tanggal"].dt.to_period("W").apply(lambda p: str(p.start_time.date()))
    cutoff = df["tanggal"].max() - pd.Timedelta(weeks=12)
    df = df[df["tanggal"] >= cutoff]
    weeks = sorted(df["week"].unique())
    trend: dict = {}
    for kat in LAYERS:
        sub = df[df["kategori"] == kat]
        counts = sub.groupby("week").size()
        trend[kat] = {"weeks": weeks, "counts": [int(counts.get(w, 0)) for w in weeks]}
    return json.dumps(trend, ensure_ascii=False)

trend_json = _build_weekly_trend()

data_badge     = "DATA DUMMY" if IS_DUMMY else "DATA RESMI 2023"
data_badge_cls = "warn-dummy" if IS_DUMMY else "warn-live"

# Timestamp scraping untuk status header
_news_ts = ""
try:
    _df_ts   = pd.read_csv(PROCESSED_DIR.parent / "raw" / "news.csv")
    _news_ts = str(_df_ts["scraped_at"].max()) if "scraped_at" in _df_ts.columns else ""
except Exception:
    pass
scraped_at_iso = _news_ts
total_markers  = sum(stats[k]["markers"] for k in LAYERS)


# ---------------------------------------------------------------------------
# 5. HTML Template — index.html (UI saja, tanpa embed HTML peta)
# ---------------------------------------------------------------------------
def render_crime_type_buttons() -> str:
    parts = []
    for j, cfg in CRIME_TYPES.items():
        neon = cfg['neon']
        label = cfg['label']
        parts.append(
            f'<button class="crime-btn" data-jenis="{j}" onclick="switchCrimeType(\'{j}\',this)"'
            f' style="display:flex;align-items:center;gap:8px;padding:7px 10px;margin-bottom:3px;'
            f'background:transparent;border:1px solid rgba(255,255,255,0.07);'
            f'color:rgba(255,255,255,0.4);font-family:Share Tech Mono,monospace;'
            f'font-size:0.68rem;cursor:pointer;width:100%;text-align:left;transition:all 0.2s;"'
            f' data-neon="{neon}">&#9656; {label}</button>'
        )
    return '\n'.join(parts)


def render_sidebar_buttons() -> str:
    btns = []
    for i, (key, cfg) in enumerate(LAYERS.items()):
        active = "active" if i == 0 else ""
        btns.append(
            f'<button class="layer-btn {active}" data-key="{key}" data-neon="{cfg["neon"]}"'
            f' onclick="switchLayer(\'{key}\',this)">'
            f'<span class="icon">{cfg["icon"]}</span><span>{cfg["label"]}</span></button>'
        )
    return "\n".join(btns)


HTML = f"""<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>NEXUS // CRIME &amp; HEALTH MAP — Indonesia Surveillance</title>
<link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700;900&family=Inter:wght@400;500;600&family=Share+Tech+Mono&display=swap" rel="stylesheet"/>
<style>
  /* ── Design tokens ─────────────────────────────────────────── */
  :root {{
    --bg:        #050510;
    --panel:     #07071a;
    --panel2:    #0b0b20;
    --border:    rgba(255,255,255,0.07);
    --border-hi: rgba(255,255,255,0.15);
    --dim:       rgba(255,255,255,0.35);
    --dim2:      rgba(255,255,255,0.18);
    --neon:      #00ffff;
    --neon-glow: rgba(0,255,255,0.18);
    --radius:    4px;
    --mono:      'Share Tech Mono', monospace;
    --sans:      'Inter', sans-serif;
    --display:   'Orbitron', sans-serif;
    --transition: 0.35s cubic-bezier(.4,0,.2,1);
  }}

  /* ── Reset ─────────────────────────────────────────────────── */
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  button {{ cursor: pointer; }}

  /* ── CRT scanlines ─────────────────────────────────────────── */
  body::after {{
    content: ''; position: fixed; inset: 0; pointer-events: none; z-index: 9998;
    background: repeating-linear-gradient(
      0deg, transparent, transparent 2px,
      rgba(0,0,0,0.055) 2px, rgba(0,0,0,0.055) 4px
    );
  }}

  body {{
    background: var(--bg); color: rgba(255,255,255,0.75);
    font-family: var(--sans);
    height: 100vh; overflow: hidden;
    display: flex; flex-direction: column;
    font-size: 13px; line-height: 1.5;
  }}

  /* ── Header ────────────────────────────────────────────────── */
  header {{
    display: flex; align-items: center; justify-content: space-between;
    padding: 0 20px; height: 48px; flex-shrink: 0;
    background: var(--panel);
    border-bottom: 1px solid var(--neon);
    box-shadow: 0 1px 20px var(--neon-glow);
    z-index: 200; transition: border-color var(--transition), box-shadow var(--transition);
  }}
  .logo {{
    font-family: var(--display); font-size: 0.95rem; font-weight: 900;
    letter-spacing: 5px; color: var(--neon); transition: color var(--transition);
    display: flex; align-items: baseline; gap: 10px;
  }}
  .logo-sub {{
    font-family: var(--mono); font-size: 0.55rem; letter-spacing: 2px;
    color: var(--dim2); font-weight: 400;
  }}
  .hud-right {{
    display: flex; align-items: center; gap: 16px;
    font-family: var(--mono); font-size: 0.65rem; letter-spacing: 1px; color: var(--dim2);
  }}
  .hud-chip {{
    display: flex; align-items: center; gap: 6px;
    padding: 3px 10px; border: 1px solid var(--border); border-radius: 2px;
  }}
  .pulse {{
    width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0;
    background: var(--neon); box-shadow: 0 0 6px var(--neon);
    animation: blink 1.4s infinite; transition: background var(--transition), box-shadow var(--transition);
  }}
  @keyframes blink {{ 0%,100%{{opacity:1}} 50%{{opacity:0.1}} }}

  /* ── Layout ────────────────────────────────────────────────── */
  .main {{ display: flex; flex: 1; overflow: hidden; position: relative; }}

  /* ── Sidebar ───────────────────────────────────────────────── */
  aside {{
    width: 272px; flex-shrink: 0;
    background: var(--panel);
    border-right: 1px solid var(--border-hi);
    display: flex; flex-direction: column;
    transition: transform var(--transition), width var(--transition);
    z-index: 100;
  }}

  /* Tab nav */
  .tab-nav {{
    display: grid; grid-template-columns: repeat(3,1fr);
    border-bottom: 1px solid var(--border); flex-shrink: 0;
  }}
  .tab-btn {{
    background: transparent; border: none; border-bottom: 2px solid transparent;
    color: var(--dim2); font-family: var(--mono); font-size: 0.6rem;
    letter-spacing: 2px; padding: 10px 4px; text-align: center;
    transition: color var(--transition), border-color var(--transition);
  }}
  .tab-btn:hover {{ color: var(--dim); }}
  .tab-btn.active {{
    color: var(--neon); border-bottom-color: var(--neon);
  }}

  /* Tab panes */
  .tab-pane {{ display: none; flex: 1; overflow-y: auto; padding: 14px 12px; }}
  .tab-pane.active {{ display: block; }}
  .tab-pane::-webkit-scrollbar {{ width: 3px; }}
  .tab-pane::-webkit-scrollbar-thumb {{ background: var(--neon); border-radius: 2px; }}

  /* Section label */
  .sec {{
    font-family: var(--mono); font-size: 0.55rem; letter-spacing: 3px;
    color: var(--dim2); text-transform: uppercase;
    padding: 0 2px 8px; display: flex; align-items: center; gap: 6px;
  }}
  .sec::after {{
    content: ''; flex: 1; height: 1px; background: var(--border);
  }}

  /* Layer buttons */
  .layer-btn {{
    display: flex; align-items: center; gap: 10px;
    padding: 10px 12px; margin-bottom: 4px; width: 100%;
    background: transparent; border: 1px solid var(--border);
    color: var(--dim2); font-family: var(--mono);
    font-size: 0.7rem; letter-spacing: 0.5px; text-align: left;
    border-radius: var(--radius);
    transition: all 0.2s; position: relative; overflow: hidden;
  }}
  .layer-btn .icon {{ font-size: 1rem; flex-shrink: 0; }}
  .layer-btn .lbl {{ flex: 1; }}
  .layer-btn .cnt {{
    font-family: var(--display); font-size: 0.6rem;
    color: var(--dim2); transition: color 0.2s;
  }}
  .layer-btn::before {{
    content: ''; position: absolute; left: 0; top: 0; bottom: 0; width: 3px;
    background: transparent; transition: background 0.2s, box-shadow 0.2s;
    border-radius: var(--radius) 0 0 var(--radius);
  }}
  .layer-btn:hover, .layer-btn.active {{
    border-color: var(--neon); color: var(--neon);
    background: color-mix(in srgb, var(--neon) 5%, transparent);
  }}
  .layer-btn:hover .cnt, .layer-btn.active .cnt {{ color: var(--neon); }}
  .layer-btn.active::before, .layer-btn:hover::before {{
    background: var(--neon); box-shadow: 0 0 8px var(--neon);
  }}

  /* Divider */
  hr.div {{ border: none; border-top: 1px solid var(--border); margin: 12px 0; }}

  /* Crime type sub-buttons */
  .crime-btn {{
    display: flex; align-items: center; gap: 8px;
    padding: 8px 10px; margin-bottom: 3px; width: 100%;
    background: transparent; border: 1px solid var(--border);
    color: var(--dim2); font-family: var(--mono); font-size: 0.65rem;
    text-align: left; border-radius: var(--radius); transition: all 0.2s;
  }}
  .crime-btn:hover {{ border-color: rgba(255,255,255,0.2); color: rgba(255,255,255,0.6); }}

  /* Stats */
  .stats-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 6px; margin-bottom: 14px; }}
  .stat-card {{
    background: var(--panel2); border: 1px solid var(--border);
    padding: 10px 8px; text-align: center; border-radius: var(--radius);
    transition: border-color var(--transition);
  }}
  .stat-card:hover {{ border-color: var(--border-hi); }}
  .stat-lbl {{
    font-family: var(--mono); font-size: 0.5rem; letter-spacing: 2px;
    color: var(--dim2); text-transform: uppercase; margin-bottom: 5px;
  }}
  .stat-val {{
    font-family: var(--display); font-size: 1.1rem; font-weight: 700;
    color: var(--neon); text-shadow: 0 0 12px var(--neon-glow);
    transition: color var(--transition), text-shadow var(--transition);
    line-height: 1;
  }}
  .stat-card.wide {{ grid-column: span 2; }}

  /* Top table */
  .top-table {{ width: 100%; border-collapse: collapse; font-size: 0.7rem; }}
  .top-table th {{
    font-family: var(--mono); font-size: 0.5rem; letter-spacing: 2px;
    color: var(--dim2); text-transform: uppercase;
    padding: 4px 6px; border-bottom: 1px solid var(--border); text-align: left;
  }}
  .top-table td {{
    padding: 6px 6px; border-bottom: 1px solid rgba(255,255,255,0.03);
    color: rgba(255,255,255,0.55); font-size: 0.72rem;
  }}
  .top-table .td-rank {{ color: var(--dim2); font-size: 0.6rem; width: 20px; }}
  .top-table .td-val {{
    color: var(--neon); text-align: right;
    font-family: var(--display); font-size: 0.65rem; font-weight: 700;
  }}
  .top-table tr:hover td {{ background: rgba(255,255,255,0.02); }}

  /* Sentiment bars */
  .sent-row {{ display:flex; align-items:center; gap:8px; margin-bottom:8px; }}
  .sent-label {{ font-family: var(--mono); font-size: 0.6rem; width: 56px; color: var(--dim2); }}
  .sent-bar {{ flex:1; height:5px; background:rgba(255,255,255,0.06); border-radius:3px; overflow:hidden; }}
  .sent-fill {{ height:100%; border-radius:3px; transition:width 0.5s ease; }}
  .sent-count {{
    width: 28px; text-align: right;
    font-family: var(--display); font-size: 0.6rem; color: var(--dim);
  }}

  /* Time filter */
  .tf-group {{ display: flex; gap: 4px; flex-wrap: wrap; }}
  .tf-btn {{
    padding: 5px 10px; font-family: var(--mono); font-size: 0.62rem;
    letter-spacing: 1px; background: transparent;
    border: 1px solid var(--border); color: var(--dim2);
    border-radius: var(--radius); transition: all 0.2s;
  }}
  .tf-btn:hover, .tf-btn.active {{
    background: color-mix(in srgb, var(--neon) 10%, transparent);
    border-color: var(--neon); color: var(--neon);
  }}

  /* Marker count badge */
  .marker-badge {{
    display: flex; align-items: center; gap: 10px;
    padding: 8px 10px; border: 1px solid var(--border);
    border-radius: var(--radius); background: var(--panel2); margin-bottom: 12px;
  }}
  .marker-dot {{
    width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0;
    background: var(--neon); box-shadow: 0 0 8px var(--neon);
    animation: blink 1.8s infinite;
  }}
  .marker-num {{
    font-family: var(--display); font-size: 1rem; font-weight: 700;
    color: var(--neon); line-height: 1;
  }}
  .marker-sub {{ font-size: 0.62rem; color: var(--dim2); font-family: var(--mono); }}

  /* ── Map area ──────────────────────────────────────────────── */
  .map-wrap {{ flex: 1; position: relative; display: flex; flex-direction: column; min-width: 0; }}
  #map-frame {{ flex: 1; border: none; display: block; width: 100%; }}

  /* Corner brackets */
  .c {{ position: absolute; width: 16px; height: 16px; pointer-events: none; z-index: 10;
        transition: border-color var(--transition); }}
  .c-tl {{ top:8px; left:8px; border-top:2px solid var(--neon); border-left:2px solid var(--neon); }}
  .c-tr {{ top:8px; right:8px; border-top:2px solid var(--neon); border-right:2px solid var(--neon); }}
  .c-bl {{ bottom:8px; left:8px; border-bottom:2px solid var(--neon); border-left:2px solid var(--neon); }}
  .c-br {{ bottom:8px; right:8px; border-bottom:2px solid var(--neon); border-right:2px solid var(--neon); }}

  /* Data badge */
  .warn {{
    position: absolute; top: 14px; left: 50%; transform: translateX(-50%);
    font-family: var(--mono); font-size: 0.58rem; letter-spacing: 2px;
    padding: 4px 14px; z-index: 10; pointer-events: none; white-space: nowrap;
    border-radius: 2px;
  }}
  .warn-dummy {{ background: rgba(255,255,0,0.06); border: 1px solid rgba(255,200,0,0.3); color: #ffcc00; }}
  .warn-live  {{ background: rgba(0,255,65,0.05);  border: 1px solid rgba(0,255,65,0.25); color: #00ff41; }}

  /* HUD bottom-right */
  .hud-br {{
    position: absolute; bottom: 14px; right: 14px;
    font-family: var(--mono); font-size: 0.55rem; letter-spacing: 2px;
    color: var(--dim2); background: rgba(5,5,16,0.8); border: 1px solid var(--border);
    padding: 4px 10px; z-index: 10; pointer-events: none; backdrop-filter: blur(6px);
    border-radius: 2px;
  }}

  /* Onboarding hint */
  #map-hint {{
    position: absolute; bottom: 50px; left: 50%; transform: translateX(-50%);
    background: rgba(5,5,16,0.92); border: 1px solid var(--neon);
    font-family: var(--mono); font-size: 0.65rem; letter-spacing: 1px;
    color: var(--neon); padding: 8px 18px; z-index: 20;
    animation: hintpulse 2.5s ease-in-out infinite; border-radius: 2px;
    pointer-events: none; white-space: nowrap;
  }}
  @keyframes hintpulse {{
    0%,100% {{ opacity: 0.85; }} 50% {{ opacity: 0.4; }}
  }}
  #map-hint.hidden {{ display: none; }}

  /* Mobile sidebar toggle */
  #sidebar-toggle {{
    display: none; position: fixed; bottom: 20px; left: 20px; z-index: 500;
    width: 44px; height: 44px; border-radius: 50%;
    background: var(--panel); border: 2px solid var(--neon);
    color: var(--neon); font-size: 1.1rem;
    box-shadow: 0 0 16px var(--neon-glow);
    align-items: center; justify-content: center;
    transition: all 0.2s;
  }}
  #sidebar-toggle:hover {{ background: color-mix(in srgb, var(--neon) 12%, var(--panel)); }}

  /* ── Article panel ─────────────────────────────────────────── */
  #art-panel {{
    position: fixed; top: 0; right: -380px; width: 360px; height: 100vh;
    background: var(--panel); border-left: 1px solid var(--neon);
    box-shadow: -6px 0 32px var(--neon-glow);
    z-index: 1000; display: flex; flex-direction: column;
    transition: right 0.3s cubic-bezier(.4,0,.2,1),
                border-color var(--transition), box-shadow var(--transition);
    overflow: hidden;
  }}
  #art-panel.open {{ right: 0; }}
  #art-panel-header {{
    padding: 14px 16px; border-bottom: 1px solid var(--border);
    display: flex; justify-content: space-between; align-items: center; flex-shrink: 0;
    background: var(--panel2);
  }}
  #art-panel-title {{
    font-family: var(--display); font-size: 0.78rem; font-weight: 700;
    color: var(--neon); letter-spacing: 2px;
  }}
  #art-panel-count {{
    font-family: var(--mono); font-size: 0.58rem;
    color: var(--dim2); margin-top: 2px;
  }}
  #art-panel-close {{
    background: transparent; border: 1px solid var(--border);
    color: var(--dim2); font-size: 0.8rem; padding: 4px 10px;
    border-radius: var(--radius); transition: all 0.2s; font-family: var(--mono);
  }}
  #art-panel-close:hover {{ border-color: var(--neon); color: var(--neon); }}
  .art-search-wrap {{
    padding: 8px 12px; border-bottom: 1px solid var(--border); flex-shrink: 0;
  }}
  #art-search {{
    width: 100%; background: var(--panel2); border: 1px solid var(--border);
    color: rgba(255,255,255,0.75); font-family: var(--sans); font-size: 0.75rem;
    padding: 7px 12px; outline: none; border-radius: var(--radius);
    transition: border-color 0.2s;
  }}
  #art-search::placeholder {{ color: var(--dim2); }}
  #art-search:focus {{ border-color: var(--neon); }}
  #art-panel-list {{ flex: 1; overflow-y: auto; padding: 10px 12px; }}
  #art-panel-list::-webkit-scrollbar {{ width: 3px; }}
  #art-panel-list::-webkit-scrollbar-thumb {{ background: var(--neon); border-radius: 2px; }}

  /* Empty state */
  .art-empty {{
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    height: 100%; gap: 12px; text-align: center; padding: 40px 20px;
  }}
  .art-empty-icon {{ font-size: 2.5rem; opacity: 0.3; }}
  .art-empty-title {{ font-size: 0.8rem; color: var(--dim2); font-family: var(--mono); letter-spacing: 2px; }}
  .art-empty-sub {{ font-size: 0.68rem; color: rgba(255,255,255,0.2); line-height: 1.6; }}

  /* Article cards */
  .art-item {{
    border: 1px solid var(--border); border-radius: var(--radius);
    padding: 12px; margin-bottom: 8px;
    transition: border-color 0.2s, background 0.2s; cursor: default;
  }}
  .art-item:hover {{ border-color: var(--border-hi); background: rgba(255,255,255,0.02); }}
  .art-badges {{ display: flex; gap: 5px; flex-wrap: wrap; margin-bottom: 7px; }}
  .art-badge {{
    font-family: var(--mono); font-size: 0.52rem; letter-spacing: 1px;
    padding: 2px 7px; border-radius: 2px; border: 1px solid;
  }}
  .art-item-title {{
    font-size: 0.78rem; font-weight: 500; color: rgba(255,255,255,0.82);
    margin-bottom: 5px; line-height: 1.45;
  }}
  .art-item-desc {{
    font-size: 0.68rem; color: rgba(255,255,255,0.38); line-height: 1.55;
    margin-bottom: 7px; display: -webkit-box; -webkit-line-clamp: 3;
    -webkit-box-orient: vertical; overflow: hidden;
  }}
  .art-item-meta {{
    font-size: 0.6rem; color: var(--dim2); margin-bottom: 8px; font-family: var(--mono);
  }}
  .art-item-link {{
    display: inline-block; font-family: var(--mono); font-size: 0.6rem;
    letter-spacing: 1px; color: var(--neon); text-decoration: none;
    border: 1px solid color-mix(in srgb, var(--neon) 40%, transparent);
    padding: 3px 10px; border-radius: 2px;
    transition: all 0.2s;
  }}
  .art-item-link:hover {{
    background: color-mix(in srgb, var(--neon) 10%, transparent);
    border-color: var(--neon);
  }}

  /* ── Metodologi modal ─────────────────────────────────────── */
  #metod-overlay {{
    display: none; position: fixed; inset: 0; z-index: 2000;
    background: rgba(0,0,0,0.7); backdrop-filter: blur(4px);
    align-items: center; justify-content: center;
  }}
  #metod-overlay.open {{ display: flex; }}
  #metod-box {{
    background: var(--panel); border: 1px solid var(--neon);
    box-shadow: 0 0 48px var(--neon-glow);
    width: min(680px, 94vw); max-height: 80vh;
    display: flex; flex-direction: column; border-radius: var(--radius);
    overflow: hidden;
  }}
  #metod-head {{
    padding: 14px 20px; border-bottom: 1px solid var(--border);
    display: flex; justify-content: space-between; align-items: center;
    background: var(--panel2); flex-shrink: 0;
  }}
  #metod-head h2 {{
    font-family: var(--display); font-size: 0.8rem; font-weight: 700;
    color: var(--neon); letter-spacing: 3px;
  }}
  #metod-close {{
    background: transparent; border: 1px solid var(--border);
    color: var(--dim2); font-family: var(--mono); font-size: 0.75rem;
    padding: 4px 12px; border-radius: var(--radius); transition: all 0.2s;
  }}
  #metod-close:hover {{ border-color: var(--neon); color: var(--neon); }}
  #metod-body {{
    overflow-y: auto; padding: 20px 24px;
    font-size: 0.72rem; color: rgba(255,255,255,0.6); line-height: 1.8;
  }}
  #metod-body::-webkit-scrollbar {{ width: 3px; }}
  #metod-body::-webkit-scrollbar-thumb {{ background: var(--neon); }}
  #metod-body h3 {{
    font-family: var(--mono); font-size: 0.58rem; letter-spacing: 3px;
    color: var(--neon); text-transform: uppercase;
    margin: 18px 0 8px; padding-bottom: 4px;
    border-bottom: 1px solid var(--border);
  }}
  #metod-body h3:first-child {{ margin-top: 0; }}
  #metod-body p {{ margin-bottom: 8px; }}
  #metod-body ul {{ padding-left: 16px; margin-bottom: 8px; }}
  #metod-body li {{ margin-bottom: 4px; }}
  #metod-body .warn-box {{
    background: rgba(255,180,0,0.06); border: 1px solid rgba(255,180,0,0.25);
    border-radius: var(--radius); padding: 10px 14px; margin: 10px 0;
    color: rgba(255,180,0,0.75); font-size: 0.68rem;
  }}
  .metod-btn {{
    background: transparent; border: 1px solid var(--border);
    color: var(--dim2); font-family: var(--mono); font-size: 0.6rem;
    letter-spacing: 1px; padding: 3px 10px; border-radius: 2px;
    transition: all 0.2s; cursor: pointer;
  }}
  .metod-btn:hover {{ border-color: var(--neon); color: var(--neon); }}

  /* Data source badges */
  .src-tag {{
    display: inline-block; font-family: var(--mono); font-size: 0.5rem;
    letter-spacing: 1px; padding: 2px 6px; border-radius: 2px;
    border: 1px solid; margin: 2px;
  }}
  .src-resmi {{ border-color: rgba(0,255,65,0.4); color: #00ff41; background: rgba(0,255,65,0.06); }}
  .src-berita {{ border-color: rgba(255,107,53,0.4); color: #ff9955; background: rgba(255,107,53,0.06); }}

  /* Stat section header with source badge */
  .stat-section-head {{
    display: flex; align-items: center; gap: 8px; margin-bottom: 10px;
    padding-bottom: 6px; border-bottom: 1px solid var(--border);
  }}
  .stat-section-head span {{
    font-family: var(--mono); font-size: 0.52rem; letter-spacing: 2px;
    color: var(--dim2); text-transform: uppercase; flex: 1;
  }}

  /* ── Responsive ────────────────────────────────────────────── */
  @media (max-width: 768px) {{
    aside {{
      position: fixed; top: 48px; left: 0; bottom: 0;
      transform: translateX(-100%); z-index: 300;
      box-shadow: 4px 0 24px rgba(0,0,0,0.6);
    }}
    aside.open {{ transform: translateX(0); }}
    #sidebar-toggle {{ display: flex; }}
    .logo-sub {{ display: none; }}
    .hud-chip:not(:first-child) {{ display: none; }}
    #art-panel {{ width: 100%; right: -100%; }}
  }}
</style>
</head>
<body>

<!-- ── Header ──────────────────────────────────────────────── -->
<header>
  <div class="logo">
    NEXUS<span style="color:var(--neon);margin:0 2px">//</span>MAP
    <span class="logo-sub">INDONESIA CRIME &amp; HEALTH SURVEILLANCE</span>
  </div>
  <div class="hud-right">
    <div class="hud-chip" id="sys-status">
      <span class="pulse" id="sys-pulse"></span>
      <span id="sys-label">MEMUAT...</span>
    </div>
    <div class="hud-chip">
      <span style="color:var(--neon);font-family:'Orbitron',sans-serif;font-size:0.7rem" id="hud-markers">{total_markers}</span>
      <span>TITIK</span>
    </div>
    <div class="hud-chip" id="hud-age" title="Waktu scraping terakhir">—</div>
    <div class="hud-chip" id="clk" style="font-family:'Orbitron',sans-serif;color:var(--neon)">--:--:--</div>
    <button class="metod-btn" onclick="document.getElementById('metod-overlay').classList.add('open')" title="Metodologi & Limitasi Data">&#9432; METODOLOGI</button>
  </div>
</header>

<!-- ── Layout ───────────────────────────────────────────────── -->
<div class="main">

  <!-- Sidebar -->
  <aside id="sidebar">

    <!-- Tab navigation -->
    <div class="tab-nav">
      <button class="tab-btn active" onclick="switchTab('layer',this)">LAYER</button>
      <button class="tab-btn"        onclick="switchTab('stats',this)">STATISTIK</button>
      <button class="tab-btn"        onclick="switchTab('filter',this)">FILTER</button>
    </div>

    <!-- ── Tab: LAYER ─────────────────────────────────────── -->
    <div class="tab-pane active" id="tab-layer">
      <div class="sec">Data layer</div>
      {render_sidebar_buttons()}

      <div id="crime-type-panel" style="display:none">
        <hr class="div"/>
        <div class="sec">Sub-kategori</div>
        <button class="crime-btn" data-jenis="" onclick="switchCrimeType('',this)"
          style="color:#ff6b35;border-color:rgba(255,107,53,0.4);margin-bottom:4px;">
          &#9646;&nbsp; SEMUA JENIS
        </button>
        {render_crime_type_buttons()}
      </div>

      <hr class="div"/>
      <div class="sec">Sumber data</div>
      <div style="font-size:0.65rem;color:var(--dim2);line-height:1.8;">
        BPS · Kemenkes · SIMFONI-PPA<br/>
        Google News · CNN · Tempo · Antara<br/>
        Republika · Jawa Pos · Okezone
      </div>
    </div>

    <!-- ── Tab: STATISTIK ─────────────────────────────────── -->
    <div class="tab-pane" id="tab-stats">

      <!-- DATA RESMI section -->
      <div class="stat-section-head">
        <span>Data Resmi</span>
        <span class="src-tag src-resmi">&#9679; BPS / KEMENKES 2023</span>
      </div>
      <div id="stat-note" style="font-size:0.6rem;color:rgba(255,255,255,0.3);line-height:1.6;margin-bottom:10px;"></div>
      <div class="stats-grid">
        <div class="stat-card"><div class="stat-lbl">Total</div><div class="stat-val" id="s-total">—</div></div>
        <div class="stat-card"><div class="stat-lbl">Rata-rata/Prov</div><div class="stat-val" id="s-avg">—</div></div>
        <div class="stat-card"><div class="stat-lbl">Tertinggi</div><div class="stat-val" id="s-max">—</div></div>
        <div class="stat-card"><div class="stat-lbl">Terendah</div><div class="stat-val" id="s-min">—</div></div>
        <div class="stat-card" title="Rata-rata per 100.000 penduduk. Populasi: BPS Proyeksi 2023">
          <div class="stat-lbl">Per 100rb Jiwa &#9432;</div><div class="stat-val" id="s-per100k">—</div>
        </div>
        <div class="stat-card" title="Nilai tertinggi per 100.000 penduduk di antara semua provinsi">
          <div class="stat-lbl">Maks per 100rb &#9432;</div><div class="stat-val" id="s-per100k-max">—</div>
        </div>
      </div>
      <div class="sec" style="margin-top:4px;">Top 5 (kasus absolut)</div>
      <table class="top-table">
        <thead><tr><th>#</th><th>Wilayah</th><th>Kasus</th></tr></thead>
        <tbody id="top-body"></tbody>
      </table>
      <div class="sec" style="margin-top:8px;">Top 5 (per 100rb jiwa) &#9432;
        <span style="font-size:0.48rem;font-family:var(--sans);text-transform:none;letter-spacing:0;color:rgba(255,255,255,0.2)">lebih adil secara populasi</span>
      </div>
      <table class="top-table">
        <thead><tr><th>#</th><th>Wilayah</th><th>Per 100rb</th></tr></thead>
        <tbody id="top-per100k-body"></tbody>
      </table>

      <hr class="div"/>
      <!-- RISK SCORE section -->
      <div class="stat-section-head">
        <span>Risk Score Komposit</span>
        <span class="src-tag src-resmi" style="color:#ff9955;border-color:rgba(255,153,85,0.4);background:rgba(255,153,85,0.06);">&#9888; EXPERIMENTAL</span>
      </div>
      <div style="font-size:0.58rem;color:rgba(255,255,255,0.28);line-height:1.65;margin-bottom:8px;padding:8px;border:1px solid rgba(255,153,85,0.15);border-radius:var(--radius);">
        Indeks 0–100 gabungan 5 kategori. Dihitung dengan min-max normalisasi per-kapita tiap kategori, lalu dirata-rata. <strong style="color:rgba(255,153,85,0.6);">Bukan ukuran resmi.</strong> Gunakan sebagai sinyal awal, bukan kesimpulan.
      </div>
      <table class="top-table">
        <thead><tr><th>#</th><th>Provinsi</th><th>Score</th></tr></thead>
        <tbody id="risk-body"></tbody>
      </table>

      <hr class="div"/>
      <!-- BERITA section -->
      <div class="stat-section-head">
        <span>Sinyal Berita</span>
        <span class="src-tag src-berita">&#9679; RSS LIVE</span>
      </div>
      <div style="font-size:0.58rem;color:rgba(255,255,255,0.28);line-height:1.65;margin-bottom:8px;">
        Jumlah artikel per provinsi — mencerminkan <em>intensitas liputan media</em>, bukan frekuensi kejadian nyata.
      </div>
      <div class="stats-grid">
        <div class="stat-card wide">
          <div class="stat-lbl">Total artikel ter-geocode</div>
          <div class="stat-val" id="n-total">—</div>
        </div>
      </div>
      <div id="news-empty-note" style="display:none;font-size:0.6rem;color:rgba(255,180,0,0.5);padding:6px 8px;border:1px solid rgba(255,180,0,0.15);border-radius:var(--radius);margin-bottom:8px;">
        &#9888; Tidak ada berita ter-geocode untuk kategori ini. Data di atas berasal dari data resmi saja.
      </div>
      <div class="sec" style="margin-top:4px;">Top 5 provinsi</div>
      <table class="top-table">
        <thead><tr><th>#</th><th>Wilayah</th><th>Artikel</th></tr></thead>
        <tbody id="news-top-body"></tbody>
      </table>

      <hr class="div"/>
      <!-- SENTIMEN section -->
      <div class="stat-section-head">
        <span>Tone Liputan Media</span>
        <span class="src-tag src-berita">&#9679; NLP</span>
      </div>
      <div style="font-size:0.58rem;color:rgba(255,255,255,0.28);line-height:1.65;margin-bottom:8px;">
        Tone artikel berita — bukan sentimen terhadap isu. "Positif" = liputan apresiasi/solusi; "Negatif" = liputan insiden/kritik.
      </div>
      <div id="sent-panel" style="margin-top:4px;">
        <div class="sent-row">
          <span class="sent-label">Negatif</span>
          <div class="sent-bar"><div class="sent-fill" id="sent-neg" style="background:#ff4444;width:0%"></div></div>
          <span class="sent-count" id="sent-neg-n">0</span>
        </div>
        <div class="sent-row">
          <span class="sent-label">Netral</span>
          <div class="sent-bar"><div class="sent-fill" id="sent-net" style="background:#666;width:0%"></div></div>
          <span class="sent-count" id="sent-net-n">0</span>
        </div>
        <div class="sent-row">
          <span class="sent-label">Positif</span>
          <div class="sent-bar"><div class="sent-fill" id="sent-pos" style="background:#00ff41;width:0%"></div></div>
          <span class="sent-count" id="sent-pos-n">0</span>
        </div>
      </div>

      <hr class="div"/>
      <div class="sec">Tren liputan mingguan (12 minggu)</div>
      <div style="font-size:0.55rem;color:rgba(255,255,255,0.2);margin-bottom:4px;">Jumlah artikel berita per minggu</div>
      <div style="position:relative;">
        <canvas id="trend-chart" width="220" height="80" style="width:100%;display:block;"></canvas>
        <div id="trend-ymax" style="position:absolute;top:2px;right:0;font-family:var(--mono);font-size:0.5rem;color:rgba(255,255,255,0.25);"></div>
        <div id="trend-ymin" style="position:absolute;bottom:2px;right:0;font-family:var(--mono);font-size:0.5rem;color:rgba(255,255,255,0.25);">0</div>
      </div>
    </div>

    <!-- ── Tab: FILTER ────────────────────────────────────── -->
    <div class="tab-pane" id="tab-filter">

      <div class="sec">Titik kejadian</div>
      <div class="marker-badge">
        <div class="marker-dot"></div>
        <div>
          <div class="marker-num" id="marker-count">0</div>
          <div class="marker-sub">kejadian terdeteksi</div>
        </div>
      </div>

      <div class="sec">Rentang waktu</div>
      <div class="tf-group" style="margin-bottom:16px;">
        <button class="tf-btn"        onclick="setTimeFilter(7,this)">7 Hari</button>
        <button class="tf-btn"        onclick="setTimeFilter(30,this)">30 Hari</button>
        <button class="tf-btn"        onclick="setTimeFilter(90,this)">90 Hari</button>
        <button class="tf-btn active" onclick="setTimeFilter(0,this)">Semua</button>
      </div>

      <div style="font-size:0.65rem;color:var(--dim2);line-height:1.7;padding:8px 10px;
          border:1px solid var(--border);border-radius:var(--radius);">
        &#9432;&nbsp; Klik titik di peta untuk melihat detail berita.<br/>
        Klik area provinsi untuk melihat semua berita dari wilayah tersebut.
      </div>
    </div>

  </aside>

  <!-- Map area -->
  <div class="map-wrap">
    <div class="c c-tl"></div><div class="c c-tr"></div>
    <div class="c c-bl"></div><div class="c c-br"></div>
    <div class="warn {data_badge_cls}">&#9888;&nbsp;{data_badge}</div>
    <iframe id="map-frame" src="maps/kriminalitas.html" title="Peta interaktif"></iframe>
    <div id="map-hint">&#9650;&nbsp; Klik provinsi untuk melihat berita terkait</div>
    <div class="hud-br">WGS84 · EPSG:4326 · &copy; NEXUS MAP SYS</div>
  </div>
</div>

<!-- Mobile sidebar toggle -->
<button id="sidebar-toggle" onclick="toggleSidebar()" aria-label="Toggle sidebar">&#9776;</button>

<!-- ── Modal Metodologi ──────────────────────────────────────── -->
<div id="metod-overlay" onclick="if(event.target===this)this.classList.remove('open')">
  <div id="metod-box">
    <div id="metod-head">
      <h2>&#9432; METODOLOGI &amp; LIMITASI DATA</h2>
      <button id="metod-close" onclick="document.getElementById('metod-overlay').classList.remove('open')">&#10005; TUTUP</button>
    </div>
    <div id="metod-body">
      <h3>Sumber Data Resmi</h3>
      <ul>
        <li><strong>Kriminalitas Umum</strong> — BPS Statistik Kriminal 2023 (jumlah laporan polisi per provinsi, sub-kategori 7 jenis kejahatan)</li>
        <li><strong>Kekerasan Seksual</strong> — SIMFONI-PPA Kementerian PPPA 2023 (kasus terdokumentasi yang dilaporkan)</li>
        <li><strong>Penyakit Menular</strong> — Kemenkes RI 2023 (gabungan DBD, TBC, HIV/AIDS, malaria, hepatitis)</li>

      </ul>
      <div class="warn-box">&#9888; Data resmi bersifat <strong>statis tahun 2023</strong>. Data ini tidak diperbarui otomatis. Angka aktual mungkin berbeda dari data publikasi resmi terbaru.</div>

      <h3>Normalisasi Per Kapita</h3>
      <p>Angka "Per 100rb Jiwa" dihitung menggunakan <strong>Proyeksi Penduduk BPS 2023</strong> per provinsi. Untuk kriminalitas, digunakan <em>crime rate</em> resmi dari BPS Statistik Kriminal. Untuk kategori lain, dihitung manual: (jumlah kasus / populasi) × 100.000.</p>
      <p>Normalisasi ini penting karena provinsi berpenduduk besar (Jawa Timur, Jawa Barat) hampir selalu unggul secara absolut, meski tidak selalu paling berisiko per kapita.</p>

      <h3>Risk Score Komposit</h3>
      <p>Indeks eksperimental 0–100 yang menggabungkan 5 kategori dengan langkah:</p>
      <ul>
        <li>Hitung nilai per-kapita tiap kategori per provinsi</li>
        <li>Normalisasi min-max (0–1) dalam tiap kategori</li>
        <li>Rata-rata dari semua kategori yang tersedia</li>
        <li>Skala ulang ke 0–100 relatif terhadap nilai tertinggi</li>
      </ul>
      <div class="warn-box">&#9888; Risk Score <strong>bukan indikator resmi</strong> dan belum divalidasi secara statistik. Semua kategori diperlakukan setara. Gunakan hanya sebagai petunjuk awal.</div>

      <h3>Sinyal Berita (RSS)</h3>
      <p>Artikel dikumpulkan dari 40+ sumber RSS (Google News, CNN Indonesia, Tempo, Antara, Jawa Pos, Republika, Okezone). Filter kata kunci per kategori diterapkan otomatis.</p>
      <ul>
        <li><strong>Jumlah artikel ≠ jumlah kejadian.</strong> Provinsi dengan lebih banyak kantor redaksi cenderung mendapat lebih banyak liputan.</li>
        <li>Geocoding dilakukan dari teks judul/deskripsi. Artikel tanpa nama wilayah di-fallback ke koordinat ibukota provinsi.</li>

      </ul>

      <h3>Analisis Sentimen</h3>
      <p>Sentimen dianalisis menggunakan rule-based NLP (IndoBERT fallback). Label yang dihasilkan mencerminkan <strong>tone liputan media</strong>, bukan kondisi di lapangan. "Positif" berarti artikel ditulis dengan framing apresiasi/penyelesaian; "Negatif" berarti framing insiden/kritik. Ini tidak berarti situasi di lapangan membaik atau memburuk.</p>

      <h3>Limitasi Umum</h3>
      <ul>
        <li>Underreporting: tidak semua kejadian dilaporkan ke polisi atau tercatat oleh media</li>
        <li>Definisi kategori berbeda antar lembaga (mis. "penyakit menular" bisa berbeda cakupannya)</li>
        <li>Data berita real-time dan data resmi 2023 tidak sebanding — jangan dibandingkan langsung</li>
        <li>Dashboard ini dibuat untuk keperluan riset dan eksplorasi data, bukan pengambilan kebijakan</li>
      </ul>
    </div>
  </div>
</div>

<!-- ── Panel detail artikel ─────────────────────────────────── -->
<div id="art-panel">
  <div id="art-panel-header">
    <div>
      <div id="art-panel-title">ARTIKEL</div>
      <div id="art-panel-count"></div>
    </div>
    <button id="art-panel-close" onclick="closeArtPanel()">&#10005; Tutup</button>
  </div>
  <div class="art-search-wrap">
    <input id="art-search" type="text" placeholder="&#128269; Cari judul atau sumber..."
      oninput="filterArtPanel(this.value)"/>
  </div>
  <div id="art-panel-list">
    <div class="art-empty">
      <div class="art-empty-icon">&#128506;</div>
      <div class="art-empty-title">PILIH PROVINSI</div>
      <div class="art-empty-sub">Klik area provinsi di peta untuk menampilkan berita terkait dari wilayah tersebut</div>
    </div>
  </div>
</div>

<script>
const CRIME_TYPE_STATS = {crime_type_stats_json};
const STATS      = {stats_json};
const NEWS_STATS = {news_stats_json};
const LAYERS     = {layers_json};
const SENTIMEN   = {sentimen_json};
const ARTICLES   = {articles_json};
const RISK_TOP10 = {risk_json};
const TREND      = {trend_json};

let currentKey  = 'kriminalitas';
let currentDays = 0;

// ── Tab navigation ──────────────────────────────────────────────
function switchTab(id, btn) {{
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById('tab-' + id).classList.add('active');
}}

// ── Mobile sidebar toggle ───────────────────────────────────────
function toggleSidebar() {{
  document.getElementById('sidebar').classList.toggle('open');
}}

// Terima pesan dari iframe
window.addEventListener('message', function(e) {{
  if (!e.data) return;
  if (e.data.type === 'markerCount') {{
    document.getElementById('marker-count').textContent =
      Number(e.data.count).toLocaleString('id-ID');
  }}
  if (e.data.type === 'provinsiClick') {{
    openArtPanel(e.data.provinsi, e.data.articles || []);
  }}
}});

const _KAT_COLOR = {{
  kriminalitas:     '#ff6b35',
  kekerasan_seksual:'#ff00ff',
  penyakit_menular: '#00ff41',
}};
const _KAT_LABEL = {{
  kriminalitas:     'KRIMINAL',
  kekerasan_seksual:'KEK. SEKSUAL',
  penyakit_menular: 'PENYAKIT',
}};
const _SENT_COLOR = {{ positif:'#00ff41', netral:'#888', negatif:'#ff4444' }};

let _artPanelArts = [];

function _renderArtItems(arts) {{
  const list = document.getElementById('art-panel-list');
  if (!arts || arts.length === 0) {{
    list.innerHTML = '<div style="color:rgba(255,255,255,0.25);font-size:0.65rem;padding:30px 0;text-align:center;">Tidak ada artikel terdeteksi<br/>untuk wilayah ini</div>';
    return;
  }}
  list.innerHTML = arts.slice(0,50).map(a => {{
    const kat   = a.kategori || '';
    const sent  = a.sentimen || '';
    const tgl   = a.tanggal ? a.tanggal.slice(0,10) : '';
    const src   = a.sumber  || '';
    const kab   = a.kabupaten || '';
    const desk  = String(a.deskripsi||'').trim().slice(0,200);
    const katClr  = _KAT_COLOR[kat]  || 'rgba(255,255,255,0.3)';
    const katLbl  = _KAT_LABEL[kat]  || kat.toUpperCase();
    const sentClr = _SENT_COLOR[sent] || 'rgba(255,255,255,0.2)';
    const badges  = [
      kat  ? `<span style="font-size:0.55rem;padding:1px 6px;border:1px solid ${{katClr}};color:${{katClr}};letter-spacing:1px;">${{katLbl}}</span>` : '',
      sent ? `<span style="font-size:0.55rem;padding:1px 6px;border:1px solid ${{sentClr}};color:${{sentClr}};letter-spacing:1px;">${{sent.toUpperCase()}}</span>` : '',
    ].filter(Boolean).join(' ');
    const meta = [tgl, src, kab].filter(Boolean).join(' · ');
    return `<div class="art-item">
      ${{badges ? `<div style="display:flex;gap:5px;flex-wrap:wrap;margin-bottom:6px;">${{badges}}</div>` : ''}}
      <div class="art-item-title">${{String(a.judul||'').slice(0,140)}}</div>
      ${{desk ? `<div class="art-item-desc">${{desk}}</div>` : ''}}
      <div class="art-item-meta">${{meta}}</div>
      ${{a.url ? `<a class="art-item-link" href="${{a.url}}" target="_blank">BACA SELENGKAPNYA &#8594;</a>` : ''}}
    </div>`;
  }}).join('');
}}

function openArtPanel(provinsi, arts) {{
  _artPanelArts = arts || [];
  const panel   = document.getElementById('art-panel');
  const title   = document.getElementById('art-panel-title');
  const counter = document.getElementById('art-panel-count');
  title.textContent = provinsi ? provinsi.toUpperCase() : 'ARTIKEL';
  if (counter) counter.textContent = _artPanelArts.length + ' artikel ditemukan';
  const searchEl = document.getElementById('art-search');
  if (searchEl) searchEl.value = '';
  _renderArtItems(_artPanelArts);
  panel.classList.add('open');
  // Sembunyikan onboarding hint setelah pertama kali dipakai
  const hint = document.getElementById('map-hint');
  if (hint) hint.classList.add('hidden');
}}

function filterArtPanel(q) {{
  if (!q) {{ _renderArtItems(_artPanelArts); return; }}
  const ql = q.toLowerCase();
  _renderArtItems(_artPanelArts.filter(a =>
    (a.judul||'').toLowerCase().includes(ql) ||
    (a.deskripsi||'').toLowerCase().includes(ql) ||
    (a.sumber||'').toLowerCase().includes(ql)
  ));
}}

function closeArtPanel() {{
  document.getElementById('art-panel').classList.remove('open');
}}

function _sendFilter(days) {{
  try {{
    document.getElementById('map-frame').contentWindow.postMessage({{days: days}}, '*');
  }} catch(e) {{}}
}}

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

function drawTrend(key, neon) {{
  const canvas = document.getElementById('trend-chart');
  if (!canvas || !canvas.getContext) return;
  const t = (TREND && TREND[key]) ? TREND[key] : null;
  const ctx = canvas.getContext('2d');
  const W = canvas.offsetWidth || 220, H = 80;
  canvas.width = W; canvas.height = H;
  ctx.clearRect(0, 0, W, H);

  const ymaxEl = document.getElementById('trend-ymax');
  const yminEl = document.getElementById('trend-ymin');

  if (!t || !t.counts || t.counts.length < 2 || Math.max(...t.counts) === 0) {{
    ctx.fillStyle = 'rgba(255,255,255,0.12)';
    ctx.font = '10px monospace';
    ctx.fillText('Belum ada data liputan berita', 8, H/2);
    if (ymaxEl) ymaxEl.textContent = '';
    if (yminEl) yminEl.textContent = '0';
    return;
  }}
  const counts = t.counts;
  const mx = Math.max(...counts, 1);
  const padL = 4, padR = 28, padT = 6, padB = 4;
  const chartW = W - padL - padR;
  const chartH = H - padT - padB;
  const stepX  = chartW / (counts.length - 1);

  // Y-axis labels
  if (ymaxEl) ymaxEl.textContent = mx;
  if (yminEl) yminEl.textContent = '0';

  // Baseline grid
  ctx.beginPath();
  ctx.strokeStyle = 'rgba(255,255,255,0.05)';
  ctx.lineWidth = 1;
  ctx.moveTo(padL, padT + chartH/2);
  ctx.lineTo(padL + chartW, padT + chartH/2);
  ctx.stroke();

  // Fill area
  ctx.beginPath();
  ctx.moveTo(padL, padT + chartH - (counts[0]/mx)*chartH);
  counts.forEach((v,i) => ctx.lineTo(padL + i*stepX, padT + chartH - (v/mx)*chartH));
  ctx.lineTo(padL + (counts.length-1)*stepX, padT + chartH);
  ctx.lineTo(padL, padT + chartH);
  ctx.closePath();
  ctx.fillStyle = neon + '1a';
  ctx.fill();

  // Line
  ctx.beginPath();
  ctx.strokeStyle = neon;
  ctx.lineWidth = 1.5;
  counts.forEach((v,i) => {{
    const x = padL + i*stepX, y = padT + chartH - (v/mx)*chartH;
    i===0 ? ctx.moveTo(x,y) : ctx.lineTo(x,y);
  }});
  ctx.stroke();

  // Dot at max
  const maxIdx = counts.indexOf(mx);
  const dotX = padL + maxIdx*stepX, dotY = padT;
  ctx.beginPath();
  ctx.arc(dotX, dotY, 3, 0, Math.PI*2);
  ctx.fillStyle = neon;
  ctx.fill();

  // Label nilai max di dot
  ctx.fillStyle = neon;
  ctx.font = '9px monospace';
  ctx.fillText(mx, dotX - (mx >= 10 ? 8 : 4), dotY - 5);
}}

const _STAT_NOTE = {{
  kriminalitas:     'BPS Statistik Kriminal 2023 — laporan polisi per provinsi.',
  kekerasan_seksual:'SIMFONI-PPA Kemenkes PPPA 2023 — kasus terdokumentasi.',
  penyakit_menular: 'Kemenkes RI 2023 — gabungan DBD, TBC, HIV/AIDS, malaria, hepatitis.',
}};
const _HAS_BERITA = ['kriminalitas','kekerasan_seksual','penyakit_menular'];

function updateStats(s, neon, key) {{
  if (neon) document.documentElement.style.setProperty('--neon', neon);

  // Stat note per layer
  const noteEl = document.getElementById('stat-note');
  if (noteEl && key) noteEl.textContent = _STAT_NOTE[key] || '';

  document.getElementById('s-total').textContent = (s.total||0).toLocaleString('id-ID');
  document.getElementById('s-avg').textContent   = (s.avg||0).toLocaleString('id-ID');
  document.getElementById('s-max').textContent   = (s.max||0).toLocaleString('id-ID');
  document.getElementById('s-min').textContent   = (s.min||0).toLocaleString('id-ID');
  document.getElementById('s-per100k').textContent     = (s.per100k_avg||0).toLocaleString('id-ID');
  document.getElementById('s-per100k-max').textContent = (s.per100k_max||0).toLocaleString('id-ID');

  const emptyRow = '<tr><td colspan="3" style="color:rgba(255,255,255,0.2);font-size:0.65rem;padding:6px">Belum ada data</td></tr>';
  document.getElementById('top-body').innerHTML  = (s.top||[]).map(([w,k],i) =>
    `<tr><td><span class="rank">${{i+1}}.</span></td><td>${{w}}</td>
     <td class="td-val">${{Number(k).toLocaleString('id-ID')}}</td></tr>`
  ).join('') || emptyRow;
  document.getElementById('top-per100k-body').innerHTML = (s.top_per100k||[]).map(([w,k],i) =>
    `<tr><td><span class="rank">${{i+1}}.</span></td><td>${{w}}</td>
     <td class="td-val">${{Number(k).toFixed(1)}}</td></tr>`
  ).join('') || emptyRow;
  document.getElementById('risk-body').innerHTML = (RISK_TOP10||[]).map(([w,k],i) =>
    `<tr><td><span class="rank">${{i+1}}.</span></td><td>${{w}}</td>
     <td class="td-val" style="color:#ff9955">${{Number(k).toFixed(1)}}</td></tr>`
  ).join('') || emptyRow;

  // Berita section — tampilkan empty note untuk layer tanpa berita
  const hasBerita = key && _HAS_BERITA.includes(key);
  const emptyNoteEl = document.getElementById('news-empty-note');
  if (emptyNoteEl) emptyNoteEl.style.display = hasBerita ? 'none' : 'block';

  if (key && NEWS_STATS[key]) {{
    const ns = NEWS_STATS[key];
    document.getElementById('n-total').textContent = (ns.total||0).toLocaleString('id-ID');
    document.getElementById('news-top-body').innerHTML = (ns.top||[]).map(([w,k],i) =>
      `<tr><td><span class="rank">${{i+1}}.</span></td><td>${{w}}</td>
       <td class="td-val">${{Number(k).toLocaleString('id-ID')}}</td></tr>`
    ).join('') || emptyRow;
  }}
  if (key && neon) drawTrend(key, neon);
}}

function _loadMap(src) {{
  const frame = document.getElementById('map-frame');
  frame.onload = function() {{ _sendFilter(currentDays); }};
  frame.src = src;
}}

function switchLayer(key, btn) {{
  currentKey = key;
  const neon = LAYERS[key].neon;
  document.documentElement.style.setProperty('--neon', neon);
  document.querySelectorAll('.layer-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  const crimePanel = document.getElementById('crime-type-panel');
  if (crimePanel) crimePanel.style.display = key === 'kriminalitas' ? 'block' : 'none';
  updateStats(STATS[key], neon, key);
  updateSentimen(key);
  _loadMap('maps/' + key + '.html');
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

function setTimeFilter(days, btn) {{
  currentDays = days;
  document.querySelectorAll('.tf-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  _sendFilter(days);
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
    _loadMap('maps/kriminalitas.html');
  }} else {{
    const s = CRIME_TYPE_STATS[jenis] || {{}};
    updateStats(s, s.neon || neon, null);
    _loadMap('maps/crime_' + jenis + '.html');
  }}
}}

// Jam digital
setInterval(() => {{
  document.getElementById('clk').textContent =
    new Date().toLocaleTimeString('id-ID', {{hour12: false}});
}}, 1000);

// Status sistem berdasarkan usia data
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
  const diffHr  = Math.floor((Date.now() - scraped) / 3600000);
  const diffMin = Math.floor((Date.now() - scraped) / 60000);
  const diffDay = Math.floor(diffHr / 24);
  let ageStr;
  if (diffMin < 1)       ageStr = 'BARU SAJA';
  else if (diffMin < 60) ageStr = diffMin + ' MNT LALU';
  else if (diffHr < 24)  ageStr = diffHr + ' JAM LALU';
  else                   ageStr = diffDay + ' HARI LALU';
  ageEl.textContent = ageStr;
  ageEl.title = 'Scraping: ' + scraped.toLocaleString('id-ID');
  if (diffHr < 6) {{
    label.textContent = 'SYSTEM ONLINE';
    pulse.style.background = '#00ff41'; pulse.style.boxShadow = '0 0 8px #00ff41';
    label.style.color = '#00ff41';
  }} else if (diffHr < 24) {{
    label.textContent = 'DATA PERLU REFRESH';
    pulse.style.background = '#ffaa00'; pulse.style.boxShadow = '0 0 8px #ffaa00';
    label.style.color = '#ffaa00'; pulse.style.animationDuration = '0.7s';
  }} else {{
    label.textContent = 'DATA USANG';
    pulse.style.background = '#ff4444'; pulse.style.boxShadow = '0 0 8px #ff4444';
    label.style.color = '#ff4444'; pulse.style.animationDuration = '0.3s';
  }}
}}
updateSystemStatus();
setInterval(updateSystemStatus, 60000);

document.addEventListener('DOMContentLoaded', () => {{
  const firstBtn = document.querySelector('.layer-btn');
  if (firstBtn) switchLayer(firstBtn.dataset.key, firstBtn);
  updateSystemStatus();
  // Auto-hide onboarding hint setelah 8 detik
  setTimeout(() => {{
    const hint = document.getElementById('map-hint');
    if (hint && !hint.classList.contains('hidden')) hint.classList.add('hidden');
  }}, 8000);
}});
</script>
</body>
</html>"""

out = DOCS_DIR / "index.html"
out.write_text(HTML, encoding="utf-8")
print(f"\nOK index.html disimpan ({len(HTML)//1024} KB) -> {out}")
print(f"OK {len(list(MAPS_DIR.glob('*.html')))} file peta di {MAPS_DIR}")
