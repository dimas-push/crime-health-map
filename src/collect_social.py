"""
Mengambil konten dari media sosial: Telegram publik & YouTube.

Sumber yang berfungsi tanpa API berbayar:
- Telegram: scrape t.me/s/<channel> (web preview publik)
- YouTube:  YouTube Data API v3 (gratis, butuh YOUTUBE_API_KEY di .env)
- Twitter:  sudah tercakup via Google News RSS di collect_news.py

Simpan ke data/raw/social.csv
"""

import os
import re
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

warnings.filterwarnings("ignore", category=requests.packages.urllib3.exceptions.InsecureRequestWarning)  # type: ignore

load_dotenv()

RAW_DIR = Path(__file__).parent.parent / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; crime-health-map/1.0)"}

# ---------------------------------------------------------------------------
# Kata kunci per kategori
# ---------------------------------------------------------------------------
KEYWORDS = {
    "kriminalitas":      ["kriminal", "pencurian", "pembunuhan", "narkoba", "begal",
                          "korupsi", "ditangkap", "tersangka", "kejahatan"],
    "kekerasan_seksual": ["kekerasan seksual", "pelecehan", "kdrt", "rudapaksa",
                          "kekerasan anak", "trafficking"],
    "penyakit_menular":  ["DBD", "demam berdarah", "TBC", "malaria", "HIV", "wabah",
                          "penyakit menular", "epidemi"],
}

# ---------------------------------------------------------------------------
# 1. TELEGRAM — scrape web preview channel publik
# ---------------------------------------------------------------------------
TELEGRAM_CHANNELS = [
    "kompascom",
    "liputan6dotcom",
    "BNN_RI",       # Badan Narkotika Nasional
]


def _detect_kategori(teks: str) -> Optional[str]:
    teks_lower = teks.lower()
    for kat in ["kekerasan_seksual", "kriminalitas", "penyakit_menular"]:
        for kw in KEYWORDS[kat]:
            if kw.lower() in teks_lower:
                return kat
    return None


def scrape_telegram_channel(channel: str) -> list[dict]:
    """Scrape pesan terbaru dari channel Telegram publik via web preview."""
    url = f"https://t.me/s/{channel}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=12, verify=False)
        r.raise_for_status()
    except requests.RequestException as e:
        print(f"[social] Telegram @{channel} gagal: {e}")
        return []

    soup = BeautifulSoup(r.content, "html.parser")
    rows = []

    for msg_wrap in soup.find_all("div", class_="tgme_widget_message_wrap"):
        teks_el = msg_wrap.find("div", class_="tgme_widget_message_text")
        date_el = msg_wrap.find("time")
        link_el = msg_wrap.find("a", class_="tgme_widget_message_date")

        if not teks_el:
            continue

        teks = teks_el.get_text(separator=" ", strip=True)[:500]
        tanggal = date_el.get("datetime", "") if date_el else ""
        url_msg = link_el.get("href", "") if link_el else ""
        kategori = _detect_kategori(teks)

        if not kategori:
            continue

        rows.append({
            "id":        url_msg.split("/")[-1] if url_msg else "",
            "teks":      teks,
            "tanggal":   tanggal,
            "url":       url_msg,
            "sumber":    f"telegram/@{channel}",
            "platform":  "telegram",
            "kategori":  kategori,
            "likes":     0,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
        })

    print(f"[social] Telegram @{channel}: {len(rows)} pesan relevan dari {len(soup.find_all('div', class_='tgme_widget_message_wrap'))} total.")
    return rows


def collect_telegram() -> list[dict]:
    all_rows: list[dict] = []
    for ch in TELEGRAM_CHANNELS:
        rows = scrape_telegram_channel(ch)
        all_rows.extend(rows)
        time.sleep(1)
    return all_rows


# ---------------------------------------------------------------------------
# 2. YOUTUBE — YouTube Data API v3 (butuh YOUTUBE_API_KEY)
# ---------------------------------------------------------------------------
YOUTUBE_QUERIES = {
    "kriminalitas":      "kriminal pencurian narkoba Indonesia",
    "kekerasan_seksual": "kekerasan seksual Indonesia berita",
    "penyakit_menular":  "wabah penyakit menular Indonesia DBD TBC",
}


def fetch_youtube(kategori: str, max_results: int = 20) -> list[dict]:
    """Cari video YouTube terbaru menggunakan YouTube Data API v3."""
    if not YOUTUBE_API_KEY:
        print(f"[social] YOUTUBE_API_KEY tidak diset, skip YouTube {kategori}.")
        return []

    query = YOUTUBE_QUERIES.get(kategori, "")
    url = "https://www.googleapis.com/youtube/v3/search"
    params = {
        "part":        "snippet",
        "q":           query,
        "type":        "video",
        "maxResults":  max_results,
        "order":       "date",
        "relevanceLanguage": "id",
        "regionCode":  "ID",
        "key":         YOUTUBE_API_KEY,
    }

    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
    except requests.RequestException as e:
        print(f"[social] YouTube API error ({kategori}): {e}")
        return []

    rows = []
    for item in data.get("items", []):
        snippet   = item.get("snippet", {})
        video_id  = item.get("id", {}).get("videoId", "")
        judul     = snippet.get("title", "")
        deskripsi = snippet.get("description", "")[:300]
        tanggal   = snippet.get("publishedAt", "")
        channel   = snippet.get("channelTitle", "")
        teks_cek  = judul + " " + deskripsi
        kat       = _detect_kategori(teks_cek) or kategori

        rows.append({
            "id":        video_id,
            "teks":      judul + ". " + deskripsi,
            "tanggal":   tanggal,
            "url":       f"https://www.youtube.com/watch?v={video_id}",
            "sumber":    f"youtube/{channel}",
            "platform":  "youtube",
            "kategori":  kat,
            "likes":     0,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
        })

    print(f"[social] YouTube {kategori}: {len(rows)} video.")
    return rows


def collect_youtube() -> list[dict]:
    all_rows: list[dict] = []
    for kat in YOUTUBE_QUERIES:
        rows = fetch_youtube(kat)
        all_rows.extend(rows)
        time.sleep(0.5)
    return all_rows


# ---------------------------------------------------------------------------
# 3. Entry point
# ---------------------------------------------------------------------------
def collect_social() -> pd.DataFrame:
    """Kumpulkan data dari semua platform sosial yang tersedia."""
    print("=" * 50)
    print("[social] Mulai pengumpulan data media sosial ...")
    print("=" * 50)

    all_rows: list[dict] = []

    print("\n[social] Scraping Telegram ...")
    all_rows.extend(collect_telegram())

    print("\n[social] Scraping YouTube ...")
    yt_rows = collect_youtube()
    all_rows.extend(yt_rows)
    if not yt_rows:
        print("[social] YouTube skip (tidak ada API key).")
        print("[social] Untuk aktifkan: isi YOUTUBE_API_KEY di .env")
        print("[social] Cara dapat key gratis: console.cloud.google.com -> YouTube Data API v3")

    if not all_rows:
        print("[social] Tidak ada data media sosial berhasil dikumpulkan.")
        return pd.DataFrame()

    df = pd.DataFrame(all_rows)

    out = RAW_DIR / "social.csv"
    if out.exists():
        existing = pd.read_csv(out)
        df = pd.concat([existing, df], ignore_index=True)
        df = df.drop_duplicates(subset=["id", "platform"])
        print(f"\n[social] Total setelah merge: {len(df)} entri.")

    df.to_csv(out, index=False)
    print(f"[social] Disimpan: {out}")

    print("\n[social] Ringkasan per platform:")
    if "platform" in df.columns:
        print(df.groupby(["platform", "kategori"]).size().to_string())

    return df


if __name__ == "__main__":
    collect_social()
