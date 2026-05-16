"""
Membersihkan, menormalisasi, dan menggabungkan semua sumber data ke SQLite.

Pipeline:
1. Load CSV dari data/raw/
2. Normalisasi nama provinsi ke nama resmi BPS
3. Agregasi data berita & tweet per provinsi per kategori
4. Gabungkan dengan data resmi sebagai base
5. Simpan ke SQLite (data/processed/crime_health.db)
6. Export tabel final ke data/processed/final.csv untuk peta
"""

import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

_CURRENT_YEAR = str(datetime.now().year)

RAW_DIR       = Path(__file__).parent.parent / "data" / "raw"
PROCESSED_DIR = Path(__file__).parent.parent / "data" / "processed"
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH  = PROCESSED_DIR / "crime_health.db"
CSV_PATH = PROCESSED_DIR / "final.csv"

# ---------------------------------------------------------------------------
# Tabel normalisasi nama provinsi (berbagai ejaan → nama resmi BPS)
# ---------------------------------------------------------------------------
PROV_NORMALIZE = {
    # Alias umum
    "jakarta":                   "DKI Jakarta",
    "dki jakarta":               "DKI Jakarta",
    "yogyakarta":                "DI Yogyakarta",
    "di yogyakarta":             "DI Yogyakarta",
    "bangka belitung":           "Kepulauan Bangka Belitung",
    "kepulauan bangka belitung": "Kepulauan Bangka Belitung",
    "kepri":                     "Kepulauan Riau",
    "ntb":                       "Nusa Tenggara Barat",
    "ntt":                       "Nusa Tenggara Timur",
    "kalbar":                    "Kalimantan Barat",
    "kalteng":                   "Kalimantan Tengah",
    "kalsel":                    "Kalimantan Selatan",
    "kaltim":                    "Kalimantan Timur",
    "kaltara":                   "Kalimantan Utara",
    "sulut":                     "Sulawesi Utara",
    "sulteng":                   "Sulawesi Tengah",
    "sulsel":                    "Sulawesi Selatan",
    "sultra":                    "Sulawesi Tenggara",
    "sulbar":                    "Sulawesi Barat",
    "malut":                     "Maluku Utara",
    "papua barat":               "Papua Barat",
    "sumut":                     "Sumatera Utara",
    "sumbar":                    "Sumatera Barat",
    "sumsel":                    "Sumatera Selatan",
    "jabar":                     "Jawa Barat",
    "jateng":                    "Jawa Tengah",
    "jatim":                     "Jawa Timur",
    # Alias yang sebelumnya hilang
    "aceh":                      "Aceh",
    "nad":                       "Aceh",
    "nanggroe aceh darussalam":  "Aceh",
    "riau":                      "Riau",
    "jambi":                     "Jambi",
    "bengkulu":                  "Bengkulu",
    "lampung":                   "Lampung",
    "banten":                    "Banten",
    "bali":                      "Bali",
    "gorontalo":                 "Gorontalo",
    "maluku":                    "Maluku",
    "papua":                     "Papua",
    "papua barat daya":          "Papua Barat",
}

# Nama resmi 34 provinsi
PROVINSI_RESMI = [
    "Aceh", "Sumatera Utara", "Sumatera Barat", "Riau", "Jambi",
    "Sumatera Selatan", "Bengkulu", "Lampung", "Kepulauan Bangka Belitung",
    "Kepulauan Riau", "DKI Jakarta", "Jawa Barat", "Jawa Tengah",
    "DI Yogyakarta", "Jawa Timur", "Banten", "Bali",
    "Nusa Tenggara Barat", "Nusa Tenggara Timur", "Kalimantan Barat",
    "Kalimantan Tengah", "Kalimantan Selatan", "Kalimantan Timur",
    "Kalimantan Utara", "Sulawesi Utara", "Sulawesi Tengah",
    "Sulawesi Selatan", "Sulawesi Tenggara", "Gorontalo", "Sulawesi Barat",
    "Maluku", "Maluku Utara", "Papua Barat", "Papua",
]


def normalize_provinsi(nama: Optional[str]) -> Optional[str]:
    """Normalisasi nama provinsi ke nama resmi BPS."""
    if not nama or pd.isna(nama):
        return None

    nama_clean = str(nama).strip().lower()

    # Cek alias langsung
    if nama_clean in PROV_NORMALIZE:
        return PROV_NORMALIZE[nama_clean]

    # Cek kecocokan parsial dengan nama resmi
    for resmi in PROVINSI_RESMI:
        if resmi.lower() in nama_clean or nama_clean in resmi.lower():
            return resmi

    return None


def clean_text(teks: str) -> str:
    """Bersihkan teks dari karakter tidak perlu."""
    if not teks or pd.isna(teks):
        return ""
    teks = str(teks)
    teks = re.sub(r"http\S+", "", teks)          # hapus URL
    teks = re.sub(r"@\w+", "", teks)             # hapus mention
    teks = re.sub(r"#\w+", "", teks)             # hapus hashtag
    teks = re.sub(r"[^\w\s.,!?]", " ", teks)    # hapus karakter aneh
    teks = re.sub(r"\s+", " ", teks).strip()
    return teks


# ---------------------------------------------------------------------------
# Load & clean tiap sumber
# ---------------------------------------------------------------------------
def load_official() -> pd.DataFrame:
    """Load data resmi (3 kategori) dan gabungkan."""
    dfs = []
    for kategori in ["kriminalitas", "penyakit_menular", "kekerasan_seksual"]:
        path = RAW_DIR / f"{kategori}.csv"
        if not path.exists():
            print(f"[process] File tidak ditemukan: {path}, skip.")
            continue
        df = pd.read_csv(path)
        df["kategori"] = kategori
        dfs.append(df)

    if not dfs:
        return pd.DataFrame()

    combined = pd.concat(dfs, ignore_index=True)
    combined["nama_provinsi"] = combined["nama_provinsi"].apply(normalize_provinsi)
    combined = combined[combined["nama_provinsi"].notna()]
    combined = combined.rename(columns={"nilai": "jumlah_kasus"})
    combined["sumber_tipe"] = "official"
    return combined[["nama_provinsi", "kategori", "jumlah_kasus", "tahun", "sumber", "sumber_tipe"]]


def load_news() -> pd.DataFrame:
    """Load data berita dan hitung frekuensi sebagai sinyal pendukung."""
    path = RAW_DIR / "news.csv"
    if not path.exists():
        print("[process] news.csv tidak ditemukan, skip.")
        return pd.DataFrame()

    df = pd.read_csv(path)
    df["provinsi"] = df["provinsi"].apply(normalize_provinsi)
    df = df[df["provinsi"].notna() & df["kategori"].notna()]
    df["judul"] = df["judul"].apply(clean_text)

    # Agregasi: hitung jumlah artikel per provinsi per kategori sebagai bobot
    agg = (
        df.groupby(["provinsi", "kategori"])
        .agg(jumlah_artikel=("judul", "count"))
        .reset_index()
        .rename(columns={"provinsi": "nama_provinsi"})
    )
    agg["sumber_tipe"] = "news"
    agg["sumber"]      = "RSS"
    agg["tahun"]       = _CURRENT_YEAR
    return agg


def load_tweets() -> pd.DataFrame:
    """Load data sosial media dari social.csv dan hitung frekuensi per provinsi per kategori."""
    path = RAW_DIR / "social.csv"
    if not path.exists():
        print("[process] social.csv tidak ditemukan, skip.")
        return pd.DataFrame()

    df = pd.read_csv(path)
    if "kategori" not in df.columns or "teks" not in df.columns:
        print("[process] social.csv tidak memiliki kolom yang diharapkan, skip.")
        return pd.DataFrame()

    # social.csv tidak punya kolom provinsi — deteksi dari teks menggunakan nama provinsi resmi
    def _extract_provinsi(teks: str) -> str | None:
        if not teks or pd.isna(teks):
            return None
        teks_lower = str(teks).lower()
        for p in PROVINSI_RESMI:
            if p.lower() in teks_lower:
                return p
        return None

    df["provinsi"] = df["teks"].apply(_extract_provinsi)
    df = df[df["provinsi"].notna() & df["kategori"].notna()]
    df["teks"] = df["teks"].apply(clean_text)

    agg = (
        df.groupby(["provinsi", "kategori"])
        .agg(jumlah_tweet=("teks", "count"))
        .reset_index()
        .rename(columns={"provinsi": "nama_provinsi"})
    )
    agg["sumber_tipe"] = "social"
    agg["sumber"]      = "SosialMedia"
    agg["tahun"]       = _CURRENT_YEAR
    return agg


# ---------------------------------------------------------------------------
# Gabungkan & simpan
# ---------------------------------------------------------------------------
def build_final_table(
    official: pd.DataFrame,
    news: pd.DataFrame,
    tweets: pd.DataFrame,
) -> pd.DataFrame:
    """
    Bangun tabel final per provinsi per kategori.

    Kolom output:
    - nama_provinsi, kategori, jumlah_kasus (resmi),
      jumlah_artikel (berita), jumlah_tweet (sosmed), tahun
    """
    # Base: semua kombinasi provinsi × kategori
    base = pd.DataFrame([
        {"nama_provinsi": p, "kategori": k}
        for p in PROVINSI_RESMI
        for k in ["kriminalitas", "kekerasan_seksual", "penyakit_menular",
                   "kecelakaan_lalin", "stunting"]
    ])

    # Merge data resmi
    if not official.empty:
        off = official[["nama_provinsi", "kategori", "jumlah_kasus"]].copy()
        base = base.merge(off, on=["nama_provinsi", "kategori"], how="left")
    else:
        base["jumlah_kasus"] = 0

    # Merge data berita
    if not news.empty:
        nws = news[["nama_provinsi", "kategori", "jumlah_artikel"]].copy()
        base = base.merge(nws, on=["nama_provinsi", "kategori"], how="left")
    else:
        base["jumlah_artikel"] = 0

    # Merge data tweet
    if not tweets.empty:
        twt = tweets[["nama_provinsi", "kategori", "jumlah_tweet"]].copy()
        base = base.merge(twt, on=["nama_provinsi", "kategori"], how="left")
    else:
        base["jumlah_tweet"] = 0

    base["jumlah_kasus"]   = base["jumlah_kasus"].fillna(0).astype(int)
    base["jumlah_artikel"] = base["jumlah_artikel"].fillna(0).astype(int)
    base["jumlah_tweet"]   = base["jumlah_tweet"].fillna(0).astype(int)
    base["tahun"]          = "2023"
    return base


def load_kecelakaan_lalin() -> pd.DataFrame:
    """Load data kecelakaan lalu lintas dari kecelakaan_lalin.csv."""
    path = RAW_DIR / "kecelakaan_lalin.csv"
    if not path.exists():
        print(f"[process] kecelakaan_lalin.csv tidak ditemukan, skip.")
        return pd.DataFrame()
    df = pd.read_csv(path)
    df["nama_provinsi"] = df["nama_provinsi"].apply(normalize_provinsi)
    df = df[df["nama_provinsi"].notna()]
    df = df.rename(columns={"jumlah_kecelakaan": "jumlah_kasus"})
    df["kategori"]    = "kecelakaan_lalin"
    df["sumber_tipe"] = "official"
    return df[["nama_provinsi", "kategori", "jumlah_kasus", "tahun", "sumber", "sumber_tipe"]]


def load_stunting() -> pd.DataFrame:
    """Load data stunting dari stunting.csv (jumlah balita stunting)."""
    path = RAW_DIR / "stunting.csv"
    if not path.exists():
        print(f"[process] stunting.csv tidak ditemukan, skip.")
        return pd.DataFrame()
    df = pd.read_csv(path)
    df["nama_provinsi"] = df["nama_provinsi"].apply(normalize_provinsi)
    df = df[df["nama_provinsi"].notna()]
    df = df.rename(columns={"jumlah_balita_stunting": "jumlah_kasus"})
    df["kategori"]    = "stunting"
    df["sumber_tipe"] = "official"
    return df[["nama_provinsi", "kategori", "jumlah_kasus", "tahun", "sumber", "sumber_tipe"]]


def load_crime_detail() -> pd.DataFrame:
    """Load kriminalitas_detail.csv untuk peta sub-kategori kejahatan."""
    path = RAW_DIR / "kriminalitas_detail.csv"
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path)
    df["nama_provinsi"] = df["nama_provinsi"].apply(normalize_provinsi)
    df = df[df["nama_provinsi"].notna()]
    # Normalize column name: lama='jumlah', baru='jumlah_kasus'
    if "jumlah" in df.columns and "jumlah_kasus" not in df.columns:
        df = df.rename(columns={"jumlah": "jumlah_kasus"})
    return df


_PROV_COORDS: dict[str, tuple[float, float]] = {
    "Aceh": (-5.5484, 95.3238), "Sumatera Utara": (3.5833, 98.6667),
    "Sumatera Barat": (-0.9492, 100.3543), "Riau": (0.5071, 101.4478),
    "Jambi": (-1.6101, 103.6131), "Sumatera Selatan": (-2.9908, 104.7565),
    "Bengkulu": (-3.8004, 102.2655), "Lampung": (-5.4295, 105.2610),
    "Kepulauan Bangka Belitung": (-2.1270, 106.1128),
    "Kepulauan Riau": (0.9169, 104.4782), "DKI Jakarta": (-6.2088, 106.8456),
    "Jawa Barat": (-6.9175, 107.6191), "Jawa Tengah": (-6.9932, 110.4229),
    "DI Yogyakarta": (-7.7956, 110.3695), "Jawa Timur": (-7.2575, 112.7521),
    "Banten": (-6.4058, 106.0640), "Bali": (-8.6500, 115.2167),
    "Nusa Tenggara Barat": (-8.5833, 116.1167),
    "Nusa Tenggara Timur": (-8.5574, 121.0794),
    "Kalimantan Barat": (-0.0226, 109.3425), "Kalimantan Tengah": (-1.6814, 113.3824),
    "Kalimantan Selatan": (-3.3194, 114.5908), "Kalimantan Timur": (-0.5022, 117.1536),
    "Kalimantan Utara": (3.0731, 116.0413), "Sulawesi Utara": (1.4748, 124.8421),
    "Sulawesi Tengah": (-0.9003, 119.8779), "Sulawesi Selatan": (-5.1477, 119.4327),
    "Sulawesi Tenggara": (-4.1462, 122.1746), "Gorontalo": (0.5435, 123.0568),
    "Sulawesi Barat": (-2.8441, 119.2321), "Maluku": (-3.6954, 128.1814),
    "Maluku Utara": (0.7893, 127.5814), "Papua Barat": (-1.3361, 133.1747),
    "Papua": (-4.2699, 138.0804),
}


def load_articles_full() -> pd.DataFrame:
    """
    Load artikel dari news.csv untuk tabel marker.
    Artikel dengan provinsi tapi tanpa koordinat di-fallback ke koordinat ibukota provinsi.
    """
    path = RAW_DIR / "news.csv"
    if not path.exists():
        return pd.DataFrame()

    df = pd.read_csv(path)
    df["provinsi"]  = df["provinsi"].apply(normalize_provinsi)
    df["judul"]     = df["judul"].apply(clean_text)
    df["deskripsi"] = df["deskripsi"].apply(clean_text) if "deskripsi" in df.columns else ""

    # Isi koordinat yang kosong menggunakan ibukota provinsi
    missing_coords = df["lat"].isna() & df["provinsi"].notna()
    for prov, coords in _PROV_COORDS.items():
        mask = missing_coords & (df["provinsi"] == prov)
        df.loc[mask, "lat"] = coords[0]
        df.loc[mask, "lon"] = coords[1]

    df = df[df["lat"].notna() & df["lon"].notna()].copy()
    before_recover = (df["lat"].notna()).sum()
    print(f"[process] {before_recover}/{len(df)+missing_coords.sum()} artikel dengan koordinat (termasuk recovery ibukota prov).")
    return df[[
        "judul", "deskripsi", "url", "tanggal", "sumber",
        "kategori", "provinsi", "kabupaten", "lat", "lon", "scraped_at",
    ]]


def save_to_sqlite(df_official: pd.DataFrame, df_news: pd.DataFrame,
                   df_tweets: pd.DataFrame, df_final: pd.DataFrame,
                   df_articles: pd.DataFrame,
                   df_crime_detail: pd.DataFrame = pd.DataFrame()) -> None:
    """Simpan semua tabel ke SQLite."""
    with sqlite3.connect(DB_PATH) as conn:
        if not df_official.empty:
            df_official.to_sql("data_resmi", conn, if_exists="replace", index=False)
        if not df_news.empty:
            df_news.to_sql("data_berita", conn, if_exists="replace", index=False)
        if not df_tweets.empty:
            df_tweets.to_sql("data_tweet", conn, if_exists="replace", index=False)
        df_final.to_sql("data_final", conn, if_exists="replace", index=False)
        if not df_articles.empty:
            df_articles.to_sql("artikel", conn, if_exists="replace", index=False)
            print(f"[process] {len(df_articles)} artikel dengan koordinat disimpan ke tabel 'artikel'.")
        if not df_crime_detail.empty:
            df_crime_detail.to_sql("kriminalitas_detail", conn, if_exists="replace", index=False)
            print(f"[process] {len(df_crime_detail)} baris kriminalitas_detail disimpan ke SQLite.")
    print(f"[process] Database disimpan: {DB_PATH}")


def process_all() -> pd.DataFrame:
    """Jalankan pipeline lengkap dan kembalikan DataFrame final."""
    print("=" * 50)
    print("[process] Memulai pipeline pemrosesan data ...")
    print("=" * 50)

    print("\n[process] Load data resmi ...")
    official = load_official()
    print(f"  {len(official)} baris data resmi (3 kategori utama).")

    print("\n[process] Load kecelakaan lalu lintas ...")
    df_lalin = load_kecelakaan_lalin()
    print(f"  {len(df_lalin)} baris kecelakaan_lalin.")

    print("\n[process] Load stunting ...")
    df_stunting = load_stunting()
    print(f"  {len(df_stunting)} baris stunting.")

    official = pd.concat([official, df_lalin, df_stunting], ignore_index=True)
    print(f"  Total official setelah merge: {len(official)} baris.")

    print("\n[process] Load data berita ...")
    news = load_news()
    print(f"  {len(news)} baris agregasi berita.")

    print("\n[process] Load data tweet ...")
    tweets = load_tweets()
    print(f"  {len(tweets)} baris agregasi tweet.")

    print("\n[process] Load artikel lengkap (dengan koordinat) ...")
    articles = load_articles_full()
    print(f"  {len(articles)} artikel dengan koordinat.")

    print("\n[process] Load kriminalitas detail ...")
    crime_detail = load_crime_detail()
    print(f"  {len(crime_detail)} baris detail kejahatan.")

    print("\n[process] Membangun tabel final ...")
    final = build_final_table(official, news, tweets)

    save_to_sqlite(official, news, tweets, final, articles, crime_detail)

    final.to_csv(CSV_PATH, index=False)
    print(f"[process] CSV final disimpan: {CSV_PATH}")

    print(f"\n[process] Selesai. {len(final)} baris ({len(PROVINSI_RESMI)} prov x 5 kategori).")
    print(final.groupby("kategori")[["jumlah_kasus", "jumlah_artikel", "jumlah_tweet"]].sum().to_string())

    return final


if __name__ == "__main__":
    process_all()
