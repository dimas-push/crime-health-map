"""
Scraping berita kriminalitas dan kesehatan dari Kompas & Detik.

Strategi:
- Gunakan RSS feed publik (tidak memerlukan autentikasi).
- Filter artikel berdasarkan kata kunci per kategori.
- Ekstrak provinsi dari teks judul/deskripsi.
- Simpan ke data/raw/news.csv
"""

import re
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
import requests
from bs4 import BeautifulSoup

RAW_DIR = Path(__file__).parent.parent / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# RSS feed publik
# ---------------------------------------------------------------------------
RSS_FEEDS = {
    "cnnindonesia_nasional":  "https://www.cnnindonesia.com/nasional/rss",
    "cnnindonesia_gaya":      "https://www.cnnindonesia.com/gaya-hidup/rss",
    "cnnindonesia_regional":  "https://www.cnnindonesia.com/regional/rss",
    "antaranews_hukum":       "https://www.antaranews.com/rss/hukum",
    "antaranews_nusantara":   "https://www.antaranews.com/rss/nusantara",
    "republika_nasional":     "https://www.republika.co.id/rss/nasional",
    "republika_peristiwa":    "https://www.republika.co.id/rss/nasional/peristiwa",
}

# ---------------------------------------------------------------------------
# Kata kunci per kategori
# ---------------------------------------------------------------------------
KEYWORDS = {
    "kriminalitas": [
        "kriminal", "pencurian", "pembunuhan", "penganiayaan", "perampokan",
        "narkoba", "penipuan", "korupsi", "begal", "curanmor", "kejahatan",
        "tindak pidana", "polisi tangkap", "tersangka", "ditangkap",
    ],
    "kekerasan_seksual": [
        "kekerasan seksual", "pelecehan seksual", "pemerkosaan", "perkosaan",
        "rudapaksa", "cabul", "kemenpppa", "simfoni", "kdrt", "kekerasan perempuan",
        "kekerasan anak", "trafficking", "perdagangan orang", "eksploitasi anak",
        "pelecehan", "pencabulan", "pelecehan terhadap", "korban kekerasan",
        "perlindungan anak", "komnas perempuan", "lpsk", "pkdrt",
        "kekerasan dalam rumah tangga", "perundungan seksual",
    ],
    "penyakit_menular": [
        "penyakit menular", "wabah", "epidemi", "pandemi", "DBD", "demam berdarah",
        "tuberculosis", "TBC", "malaria", "HIV", "AIDS", "hepatitis", "kolera",
        "campak", "polio", "cacar", "kemenkes", "puskesmas",
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
            "deskripsi": BeautifulSoup(
                desc.get_text(strip=True) if desc else "", "html.parser"
            ).get_text(strip=True)[:300],
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

    # Buang artikel yang tidak relevan (tidak ada kategori terdeteksi)
    df = df[df["kategori"].notna()].copy()
    df = df.drop(columns=["teks_gabung"])
    df["scraped_at"] = datetime.now().isoformat()

    print(f"[collect_news] {len(df)} artikel relevan dari {len(all_items)} total.")
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
