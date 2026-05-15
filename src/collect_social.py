"""
Mengambil tweet dari Twitter/X API v2 menggunakan Tweepy.

Strategi:
- Search recent tweets dengan query keyword per kategori.
- Filter tweet berbahasa Indonesia.
- Simpan teks mentah ke data/raw/tweets.csv untuk diproses sentiment.py.
- Jika bearer token tidak ada, gunakan data sampel untuk dev/testing.
"""

import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

RAW_DIR = Path(__file__).parent.parent / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

BEARER_TOKEN = os.getenv("TWITTER_BEARER_TOKEN", "")

# ---------------------------------------------------------------------------
# Query pencarian per kategori (operator Twitter API v2)
# ---------------------------------------------------------------------------
SEARCH_QUERIES = {
    "kriminalitas": (
        "(kriminal OR pencurian OR pembunuhan OR begal OR narkoba OR kejahatan) "
        "lang:id -is:retweet"
    ),
    "kekerasan_seksual": (
        "(\"kekerasan seksual\" OR \"pelecehan seksual\" OR kdrt OR "
        "\"kekerasan perempuan\" OR \"kekerasan anak\") "
        "lang:id -is:retweet"
    ),
    "penyakit_menular": (
        "(DBD OR \"demam berdarah\" OR TBC OR malaria OR wabah OR "
        "\"penyakit menular\" OR hepatitis) "
        "lang:id -is:retweet"
    ),
}

MAX_RESULTS_PER_QUERY = 50  # maks 100 untuk Basic tier


def _build_client():
    """Buat Tweepy Client jika bearer token tersedia."""
    try:
        import tweepy
        return tweepy.Client(bearer_token=BEARER_TOKEN, wait_on_rate_limit=True)
    except ImportError:
        print("[collect_social] tweepy tidak terinstall.")
        return None


def fetch_tweets(kategori: str, max_results: int = MAX_RESULTS_PER_QUERY) -> list[dict]:
    """
    Ambil tweet terbaru untuk satu kategori.
    Kembalikan list dict siap jadi DataFrame.
    """
    if not BEARER_TOKEN:
        print(f"[collect_social] TWITTER_BEARER_TOKEN tidak diset, skip {kategori}.")
        return []

    client = _build_client()
    if client is None:
        return []

    query = SEARCH_QUERIES[kategori]
    print(f"[collect_social] Mencari tweet: {kategori} ...")

    try:
        import tweepy
        response = client.search_recent_tweets(
            query=query,
            max_results=max_results,
            tweet_fields=["created_at", "lang", "public_metrics", "geo"],
            expansions=["geo.place_id"],
            place_fields=["full_name", "country_code"],
        )
    except tweepy.TweepyException as e:
        print(f"[collect_social] Error Twitter API: {e}")
        return []

    if not response.data:
        print(f"[collect_social] Tidak ada tweet untuk {kategori}.")
        return []

    # Mapping place_id → nama tempat
    places = {}
    if response.includes and "places" in response.includes:
        for place in response.includes["places"]:
            places[place.id] = place.full_name

    rows = []
    for tweet in response.data:
        geo_name = None
        if tweet.geo and "place_id" in tweet.geo:
            geo_name = places.get(tweet.geo["place_id"])

        rows.append({
            "tweet_id":   str(tweet.id),
            "teks":       tweet.text,
            "created_at": str(tweet.created_at),
            "kategori":   kategori,
            "lokasi_geo": geo_name,
            "likes":      tweet.public_metrics.get("like_count", 0),
            "retweets":   tweet.public_metrics.get("retweet_count", 0),
            "sumber":     "twitter",
            "scraped_at": datetime.now(timezone.utc).isoformat(),
        })

    print(f"[collect_social]   {len(rows)} tweet diperoleh untuk {kategori}.")
    return rows


# ---------------------------------------------------------------------------
# Data sampel — digunakan saat token tidak tersedia (dev mode)
# ---------------------------------------------------------------------------
_SAMPLE_TWEETS = [
    {"teks": "Polisi berhasil menangkap pelaku pencurian motor di Bandung, Jawa Barat. Tersangka sudah diamankan.", "kategori": "kriminalitas", "lokasi_geo": "Bandung, Jawa Barat"},
    {"teks": "Kasus begal meningkat di wilayah Surabaya. Warga diminta waspada saat berkendara malam hari.", "kategori": "kriminalitas", "lokasi_geo": "Surabaya, Jawa Timur"},
    {"teks": "Peredaran narkoba di Medan semakin mengkhawatirkan. BNN gelar operasi besar-besaran.", "kategori": "kriminalitas", "lokasi_geo": "Medan, Sumatera Utara"},
    {"teks": "Kasus DBD di Jakarta meningkat drastis minggu ini. Dinkes DKI imbau warga bersihkan lingkungan.", "kategori": "penyakit_menular", "lokasi_geo": "Jakarta, DKI Jakarta"},
    {"teks": "Wabah TBC masih jadi masalah serius di Jawa Barat. Ribuan pasien baru terdeteksi tahun ini.", "kategori": "penyakit_menular", "lokasi_geo": "Bandung, Jawa Barat"},
    {"teks": "Kasus kekerasan seksual terhadap anak di Sulawesi Selatan dilaporkan meningkat. KPAI minta penanganan serius.", "kategori": "kekerasan_seksual", "lokasi_geo": "Makassar, Sulawesi Selatan"},
    {"teks": "Pelaku penipuan online ditangkap polisi di Semarang. Korban tersebar di berbagai provinsi.", "kategori": "kriminalitas", "lokasi_geo": "Semarang, Jawa Tengah"},
    {"teks": "Malaria kembali merebak di Papua. Kemenkes kirim tim medis dan obat-obatan ke daerah terpencil.", "kategori": "penyakit_menular", "lokasi_geo": "Jayapura, Papua"},
    {"teks": "KDRT dilaporkan meningkat pasca pandemi di Bali. LBH perempuan catat kenaikan 30%.", "kategori": "kekerasan_seksual", "lokasi_geo": "Denpasar, Bali"},
    {"teks": "Pembunuhan di Medan, pelaku masih dalam pengejaran polisi. Korban ditemukan di pinggiran kota.", "kategori": "kriminalitas", "lokasi_geo": "Medan, Sumatera Utara"},
]


def load_sample_tweets() -> list[dict]:
    """Kembalikan data sampel tweet untuk mode development."""
    print("[collect_social] Menggunakan data sampel tweet (mode dev).")
    rows = []
    for i, t in enumerate(_SAMPLE_TWEETS):
        rows.append({
            "tweet_id":   f"sample_{i:04d}",
            "teks":       t["teks"],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "kategori":   t["kategori"],
            "lokasi_geo": t.get("lokasi_geo"),
            "likes":      0,
            "retweets":   0,
            "sumber":     "sample",
            "scraped_at": datetime.now(timezone.utc).isoformat(),
        })
    return rows


def collect_social() -> pd.DataFrame:
    """Entry point: ambil tweet semua kategori dan simpan ke CSV."""
    all_rows: list[dict] = []

    if BEARER_TOKEN:
        for kategori in SEARCH_QUERIES:
            rows = fetch_tweets(kategori)
            all_rows.extend(rows)
            time.sleep(2)  # hindari rate limit
    else:
        all_rows = load_sample_tweets()

    if not all_rows:
        print("[collect_social] Tidak ada tweet untuk disimpan.")
        return pd.DataFrame()

    df = pd.DataFrame(all_rows)
    out = RAW_DIR / "tweets.csv"

    if out.exists():
        existing = pd.read_csv(out)
        df = pd.concat([existing, df], ignore_index=True)
        df = df.drop_duplicates(subset=["tweet_id"])
        print(f"[collect_social] Total setelah merge: {len(df)} tweet.")

    df.to_csv(out, index=False)
    print(f"[collect_social] Disimpan: {out}")
    print("\n[collect_social] Ringkasan kategori:")
    print(df["kategori"].value_counts().to_string())
    return df


if __name__ == "__main__":
    collect_social()
