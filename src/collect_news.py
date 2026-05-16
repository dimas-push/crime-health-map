"""
Scraping berita kriminalitas dan kesehatan dari Kompas & Detik.

Strategi:
- Gunakan RSS feed publik (tidak memerlukan autentikasi).
- Filter artikel berdasarkan kata kunci per kategori.
- Ekstrak provinsi dari teks judul/deskripsi.
- Simpan ke data/raw/news.csv
"""

import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).parent))
from geocode import get_coords, _COORDS, _ALIASES, _BLACKLIST, _CONTEXT_BLACKLIST

RAW_DIR = Path(__file__).parent.parent / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# RSS feed publik
# ---------------------------------------------------------------------------
# ── Google News RSS per keyword (agregat dari 100+ sumber Indonesia) ──
_GN = "https://news.google.com/rss/search?hl=id&gl=ID&ceid=ID:id&q="

RSS_FEEDS = {
    # ── Google News per topik (multi-sumber, 100 artikel) ──────────────────
    "gnews_kriminal":         _GN + "kriminal+Indonesia+ditangkap",
    "gnews_narkoba":          _GN + "narkoba+ditangkap+tersangka",
    "gnews_pencurian":        _GN + "pencurian+begal+Indonesia",
    "gnews_pembunuhan":       _GN + "pembunuhan+tersangka+polisi",
    "gnews_korupsi":          _GN + "korupsi+KPK+ditangkap",
    "gnews_kekerasan":        _GN + "kekerasan+seksual+pelecehan",
    "gnews_penyakit":         _GN + "wabah+penyakit+menular+Indonesia",
    "gnews_dbd":              _GN + "demam+berdarah+DBD+kasus",
    "gnews_hiv":              _GN + "HIV+AIDS+kasus+Indonesia",
    "gnews_tbc":              _GN + "TBC+tuberculosis+kasus",
    "gnews_kdrt":             _GN + "KDRT+kekerasan+rumah+tangga+korban",
    "gnews_trafficking":      _GN + "trafficking+perdagangan+orang+Indonesia",
    "gnews_penipuan":         _GN + "penipuan+online+korban+polisi",
    "gnews_korupsi_daerah":   _GN + "korupsi+bupati+walikota+ditangkap",
    "gnews_pencabulan":       _GN + "pencabulan+anak+tersangka+polisi",
    "gnews_stunting":         _GN + "stunting+gizi+buruk+anak+Indonesia",
    "gnews_malaria":          _GN + "malaria+kasus+endemis+Indonesia",
    "gnews_hepatitis":        _GN + "hepatitis+kasus+Indonesia+kemenkes",
    "gnews_campak":           _GN + "campak+polio+imunisasi+KLB",
    "gnews_kecelakaan":       _GN + "kecelakaan+lalu+lintas+korban+jiwa",
    "gnews_curanmor":         _GN + "curanmor+pencurian+motor+pelaku+ditangkap",
    "gnews_perampok":         _GN + "perampokan+bersenjata+pelaku+ditangkap",
    "gnews_pengedar":         _GN + "pengedar+narkoba+sabu+ganja+ditangkap",
    "gnews_pelecehan_anak":   _GN + "pelecehan+seksual+anak+tersangka",
    # ── Tempo ──────────────────────────────────────────────────────────────
    "tempo_nasional":         "https://rss.tempo.co/nasional",
    "tempo_hukum":            "https://rss.tempo.co/hukum",
    "tempo_metro":            "https://rss.tempo.co/metro",
    "tempo_kesehatan":        "https://rss.tempo.co/kesehatan",
    # ── CNN Indonesia ───────────────────────────────────────────────────────
    "cnnindonesia_nasional":  "https://www.cnnindonesia.com/nasional/rss",
    "cnnindonesia_gaya":      "https://www.cnnindonesia.com/gaya-hidup/rss",
    # ── Antara News ────────────────────────────────────────────────────────
    "antaranews_hukum":       "https://www.antaranews.com/rss/hukum",
    "antaranews_humaniora":   "https://www.antaranews.com/rss/humaniora",
    "antaranews_kesehatan":   "https://www.antaranews.com/rss/kesehatan",
    # ── Jawa Pos ───────────────────────────────────────────────────────────
    "jawapos_nasional":       "https://www.jawapos.com/rss/nasional",
    "jawapos_metro":          "https://www.jawapos.com/rss/metro",
    # ── Republika ──────────────────────────────────────────────────────────
    "republika_nasional":     "https://www.republika.co.id/rss/nasional",
    "republika_hukum":        "https://www.republika.co.id/rss/hukum",
    # ── Media Indonesia ────────────────────────────────────────────────────
    "mediaindonesia":         "https://mediaindonesia.com/rss",
    # ── Tribun Network ─────────────────────────────────────────────────────
    "tribunnews_nasional":    "https://www.tribunnews.com/rss/nasional",
    "tribunnews_regional":    "https://www.tribunnews.com/rss/regional",
    "tribunnews_hukum":       "https://www.tribunnews.com/rss/hukum-kriminal",
    "tribunnews_kesehatan":   "https://www.tribunnews.com/rss/kesehatan",
    # ── Okezone ────────────────────────────────────────────────────────────
    "okezone_nasional":       "https://sindikasi.okezone.com/index.php/rss/1/RSS2.0",
    "okezone_kesehatan":      "https://sindikasi.okezone.com/index.php/rss/7/RSS2.0",
    # ── Liputan6 ───────────────────────────────────────────────────────────
    "liputan6_news":          "https://www.liputan6.com/rss/berita",
    "liputan6_regional":      "https://www.liputan6.com/rss/regional",
    "liputan6_kesehatan":     "https://www.liputan6.com/rss/health",
    # ── Kompas ─────────────────────────────────────────────────────────────
    "kompas_nasional":        "https://rss.kompas.com/nasional",
    "kompas_tren":            "https://rss.kompas.com/tren",
    # ── DetikNews ──────────────────────────────────────────────────────────
    "detik_news":             "https://rss.detik.com/index.php/detikcom",
    "detik_health":           "https://rss.detik.com/index.php/detikhealth",
    # ── Beritasatu ─────────────────────────────────────────────────────────
    "beritasatu_nasional":    "https://www.beritasatu.com/rss/nasional.xml",
    # ── IDN Times ──────────────────────────────────────────────────────────
    "idntimes_news":          "https://www.idntimes.com/rss/news",
}

# ---------------------------------------------------------------------------
# Kata kunci per kategori
# ---------------------------------------------------------------------------
KEYWORDS = {
    "kriminalitas": [
        "kriminal", "pencurian", "pembunuhan", "penganiayaan", "perampokan",
        "narkoba", "penipuan", "korupsi", "begal", "curanmor", "kejahatan",
        "tindak pidana", "polisi tangkap", "tersangka", "ditangkap",
        "pengedar", "sindikat", "perampok", "penculikan", "penggelapan",
        "pemalsuan", "suap", "gratifikasi", "pencucian uang", "judi online",
        "penyelundupan", "illegal fishing", "pembalakan liar", "korupsi dana",
        "teroris", "bom", "radikalisme", "eksekusi mati", "hukum pidana",
        "ditetapkan tersangka", "ditahan polisi", "vonis penjara", "dakwaan",
        "kecelakaan lalu lintas", "lakalantas", "tabrakan maut", "korban lalin",
    ],
    "kekerasan_seksual": [
        "kekerasan seksual", "pelecehan seksual", "pemerkosaan", "perkosaan",
        "rudapaksa", "cabul", "kemenpppa", "simfoni", "kdrt", "kekerasan perempuan",
        "kekerasan anak", "trafficking", "perdagangan orang", "eksploitasi anak",
        "pelecehan", "pencabulan", "pelecehan terhadap", "korban kekerasan",
        "perlindungan anak", "komnas perempuan", "lpsk", "pkdrt",
        "kekerasan dalam rumah tangga", "perundungan seksual",
        "child grooming", "konten pornografi anak", "korban pelecehan",
        "paedofil", "penganiayaan anak", "anak terlantar", "kekerasan remaja",
        "bullying", "perundungan", "eksploitasi perempuan",
    ],
    "penyakit_menular": [
        "penyakit menular", "wabah", "epidemi", "pandemi", "DBD", "demam berdarah",
        "tuberculosis", "TBC", "malaria", "HIV", "AIDS", "hepatitis", "kolera",
        "campak", "polio", "cacar", "kemenkes", "puskesmas",
        "KLB", "kejadian luar biasa", "leptospirosis", "rabies", "tifus",
        "pneumonia", "difteri", "meningitis", "chikungunya", "flu burung",
        "ISPA", "diare", "stunting", "gizi buruk", "kekurangan gizi",
        "kematian ibu", "kematian bayi", "imunisasi", "vaksinasi",
        "pos yandu", "program kesehatan", "angka kematian",
    ],
}

# Nama 34 provinsi untuk ekstraksi lokasi dari teks
PROVINSI_LIST = [
    "Aceh", "Sumatera Utara", "Sumatera Barat", "Riau", "Jambi",
    "Sumatera Selatan", "Bengkulu", "Lampung", "Bangka Belitung",
    "Kepulauan Riau", "DKI Jakarta", "Jakarta", "Jawa Barat", "Jawa Tengah",
    "DI Yogyakarta", "Yogyakarta", "Jawa Timur", "Banten", "Bali",
    "Nusa Tenggara Barat", "Nusa Tenggara Timur", "Kalimantan Barat",
    "Kalimantan Tengah", "Kalimantan Selatan", "Kalimantan Timur",
    "Kalimantan Utara", "Sulawesi Utara", "Sulawesi Tengah",
    "Sulawesi Selatan", "Sulawesi Tenggara", "Gorontalo", "Sulawesi Barat",
    "Maluku", "Maluku Utara", "Papua Barat", "Papua",
]

# Normalisasi alias ke nama resmi
PROVINSI_ALIAS = {
    "Jakarta":    "DKI Jakarta",
    "Yogyakarta": "DI Yogyakarta",
    "Bangka Belitung": "Kepulauan Bangka Belitung",
}


def _fetch_rss(url: str, timeout: int = 15) -> Optional[BeautifulSoup]:
    """Ambil dan parse RSS feed, kembalikan BeautifulSoup atau None."""
    headers = {"User-Agent": "Mozilla/5.0 (compatible; crime-health-map/1.0)"}
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
        return BeautifulSoup(resp.content, "xml")
    except requests.RequestException as e:
        print(f"[collect_news] Gagal fetch {url}: {e}")
        return None


def _parse_rss_items(soup: BeautifulSoup, source: str) -> list[dict]:
    """Ekstrak semua item dari RSS feed menjadi list dict."""
    items = []
    for item in soup.find_all("item"):
        title = item.find("title")
        desc  = item.find("description")
        link  = item.find("link")
        pub   = item.find("pubDate")

        items.append({
            "judul":   title.get_text(strip=True) if title else "",
            "deskripsi": desc.get_text(strip=True)[:300] if desc else "",
            "url":     link.get_text(strip=True) if link else "",
            "tanggal": pub.get_text(strip=True) if pub else "",
            "sumber":  source,
        })
    return items


def _detect_kategori(teks: str) -> Optional[str]:
    """Deteksi kategori artikel berdasarkan kata kunci (case-insensitive)."""
    teks_lower = teks.lower()
    # Kekerasan seksual diperiksa lebih dulu karena kata kuncinya spesifik
    for kategori in ["kekerasan_seksual", "kriminalitas", "penyakit_menular"]:
        for kw in KEYWORDS[kategori]:
            if kw.lower() in teks_lower:
                return kategori
    return None


# Daftar lookup: gabungan kamus koordinat + alias, panjang → pendek
_LOOKUP_LIST = sorted(
    list(_COORDS.keys()) + list(_ALIASES.keys()),
    key=len, reverse=True
)
# Hapus duplikat sambil pertahankan urutan
_seen: set[str] = set()
_LOOKUP_LIST = [x for x in _LOOKUP_LIST if not (x in _seen or _seen.add(x))]  # type: ignore


def _detect_kabupaten(teks: str) -> Optional[str]:
    """
    Deteksi nama kabupaten/kota dari teks berita.
    Mengembalikan nama kota yang sudah di-resolve ke kamus koordinat.
    """
    teks_lower = teks.lower()
    for nama in _LOOKUP_LIST:
        # Lewati nama yang sangat pendek (< 4 char) — rawan false positive
        if len(nama) < 4:
            continue
        # Lewati kata yang ada di blacklist
        if nama in _BLACKLIST or nama.lower() in _BLACKLIST:
            continue
        if re.search(r'\b' + re.escape(nama) + r'\b', teks_lower):
            # Cek context blacklist — hindari false positive frasa institusi
            ctx_blocked = _CONTEXT_BLACKLIST.get(nama.lower(), [])
            if any(frasa in teks_lower for frasa in ctx_blocked):
                continue
            # Resolve alias ke nama kamus
            resolved = _ALIASES.get(nama, nama)
            return resolved.title()
    return None


def _detect_provinsi(teks: str) -> Optional[str]:
    """Cari nama provinsi pertama yang muncul dalam teks."""
    for prov in PROVINSI_LIST:
        if re.search(r'\b' + re.escape(prov) + r'\b', teks, re.IGNORECASE):
            return PROVINSI_ALIAS.get(prov, prov)
    return None


def scrape_feeds() -> pd.DataFrame:
    """
    Ambil semua RSS feed, filter berdasarkan kata kunci,
    dan kembalikan DataFrame artikel yang relevan.
    """
    all_items: list[dict] = []

    for source, url in RSS_FEEDS.items():
        print(f"[collect_news] Scraping: {source} ...")
        soup = _fetch_rss(url)
        if soup is None:
            continue

        items = _parse_rss_items(soup, source)
        print(f"[collect_news]   {len(items)} item ditemukan.")
        all_items.extend(items)
        time.sleep(1)  # jeda sopan antar request

    if not all_items:
        print("[collect_news] Tidak ada artikel berhasil diambil.")
        return pd.DataFrame()

    df = pd.DataFrame(all_items)

    # Gabung judul + deskripsi untuk deteksi
    df["teks_gabung"] = df["judul"] + " " + df["deskripsi"]
    df["kategori"]    = df["teks_gabung"].apply(_detect_kategori)
    df["provinsi"]    = df["teks_gabung"].apply(_detect_provinsi)
    df["kabupaten"]   = df["teks_gabung"].apply(_detect_kabupaten)

    # Kata kunci yang menandakan berita bukan kejadian di Indonesia
    _LUAR_NEGERI = [
        "di jepang", "di china", "di malaysia", "di singapura", "di australia",
        "di korea", "di arab saudi", "di amerika", "di eropa", "di inggris",
        "di prancis", "di filipina", "di thailand", "di vietnam", "di myanmar",
        "wni di luar", "ditangkap di luar negeri", "kapal mv ", "hantavirus",
    ]

    def _resolve_location(row) -> tuple[Optional[str], Optional[float], Optional[float]]:
        kab   = row["kabupaten"]
        prov  = row["provinsi"]
        judul = str(row.get("judul") or "").lower()
        desk  = str(row.get("deskripsi") or "").lower()
        teks  = judul + " " + desk

        # Buang berita yang kejadiannya di luar negeri
        if any(frasa in teks for frasa in _LUAR_NEGERI):
            return None, None, None

        # Coba dari kabupaten dulu
        if kab and not pd.isna(kab):
            c = get_coords(str(kab).lower())
            if c:
                return str(kab), c[0], c[1]

        # Fallback ke ibukota provinsi — hanya jika nama provinsi ada di _ALIASES
        # (artinya ada mapping eksplisit provinsi → ibukota, bukan tebakan)
        if prov and not pd.isna(prov):
            prov_lower = str(prov).lower()
            if prov_lower in _ALIASES:
                c = get_coords(prov_lower)
                if c:
                    return str(prov), c[0], c[1]

        return kab, None, None

    resolved       = df.apply(_resolve_location, axis=1, result_type="expand")
    df["kabupaten"] = resolved[0]
    df["lat"]       = resolved[1]
    df["lon"]       = resolved[2]

    # Buang artikel yang tidak relevan
    df = df[df["kategori"].notna()].copy()
    df = df.drop(columns=["teks_gabung"])
    df["scraped_at"] = datetime.now().isoformat()

    print(f"[collect_news] {len(df)} artikel relevan dari {len(all_items)} total.")
    geo_count = df["lat"].notna().sum()
    print(f"[collect_news] {geo_count}/{len(df)} artikel berhasil di-geocode.")
    return df


def collect_news() -> pd.DataFrame:
    """Entry point: scrape, filter, dan simpan ke CSV."""
    df = scrape_feeds()

    if df.empty:
        print("[collect_news] Tidak ada data untuk disimpan.")
        return df

    out = RAW_DIR / "news.csv"

    # Append jika file sudah ada (hindari duplikat berdasarkan URL)
    if out.exists():
        existing = pd.read_csv(out)
        df = pd.concat([existing, df], ignore_index=True)
        df = df.drop_duplicates(subset=["url"])
        print(f"[collect_news] Total setelah merge dengan data lama: {len(df)} artikel.")

    df.to_csv(out, index=False)
    print(f"[collect_news] Disimpan: {out}")

    # Ringkasan per kategori
    print("\n[collect_news] Ringkasan kategori:")
    print(df["kategori"].value_counts().to_string())
    return df


if __name__ == "__main__":
    collect_news()
