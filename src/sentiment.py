"""
Analisis sentimen teks Bahasa Indonesia menggunakan IndoBERT.

Model: indolem/indobert-base-uncased (HuggingFace)
Fine-tuned untuk klasifikasi sentimen: positif / negatif / netral

Pipeline:
1. Load teks dari tweets.csv dan news.csv
2. Jalankan inferensi batch IndoBERT
3. Simpan hasil ke data/processed/sentiment.csv
4. Update tabel SQLite dengan kolom sentimen
"""

import sqlite3
import warnings
from pathlib import Path
from typing import Literal

import pandas as pd

warnings.filterwarnings("ignore")

RAW_DIR       = Path(__file__).parent.parent / "data" / "raw"
PROCESSED_DIR = Path(__file__).parent.parent / "data" / "processed"
DB_PATH       = PROCESSED_DIR / "crime_health.db"
SENTIMENT_CSV = PROCESSED_DIR / "sentiment.csv"

SentimentLabel = Literal["positif", "negatif", "netral"]

# ---------------------------------------------------------------------------
# Model IndoBERT — lazy load agar tidak memperlambat import
# ---------------------------------------------------------------------------
_pipeline = None

def _get_pipeline():
    """Load IndoBERT pipeline sekali, reuse selanjutnya."""
    global _pipeline
    if _pipeline is not None:
        return _pipeline

    try:
        from transformers import pipeline as hf_pipeline
        print("[sentiment] Memuat model IndoBERT ...")
        # Model sentiment Bahasa Indonesia yang sudah fine-tuned
        _pipeline = hf_pipeline(
            task="text-classification",
            model="mdhugol/indonesia-bert-sentiment-classification",
            tokenizer="mdhugol/indonesia-bert-sentiment-classification",
            device=-1,       # CPU; ganti ke 0 jika ada GPU
            truncation=True,
            max_length=512,
        )
        print("[sentiment] Model berhasil dimuat.")
        return _pipeline
    except Exception as e:
        print(f"[sentiment] Gagal memuat model HuggingFace: {e}")
        return None


# ---------------------------------------------------------------------------
# Fallback: rule-based sentiment (tanpa model)
# ---------------------------------------------------------------------------
_POSITIVE_WORDS = {
    "berhasil", "sukses", "selamat", "aman", "sembuh", "pulih", "tangkap",
    "ditangkap", "hukum", "adil", "menang", "bantu", "lindungi", "sehat",
    "baik", "meningkat", "naik", "positif", "apresiasi",
}
_NEGATIVE_WORDS = {
    "korban", "tewas", "meninggal", "mati", "marak", "tinggi", "parah",
    "bahaya", "ancam", "takut", "darurat", "krisis", "gagal", "buruk",
    "kekerasan", "perkosa", "bunuh", "rusak", "rusuh", "kacau", "naik",
    "meningkat", "bertambah", "meluas", "menyebar", "wabah",
}


def _rule_based_sentiment(teks: str) -> SentimentLabel:
    """Hitung sentimen sederhana berdasarkan kata kunci."""
    tokens = set(str(teks).lower().split())
    pos = len(tokens & _POSITIVE_WORDS)
    neg = len(tokens & _NEGATIVE_WORDS)
    if neg > pos:
        return "negatif"
    if pos > neg:
        return "positif"
    return "netral"


# ---------------------------------------------------------------------------
# Label mapping model HuggingFace → label standar
# ---------------------------------------------------------------------------
_LABEL_MAP = {
    "LABEL_0": "positif",
    "LABEL_1": "netral",
    "LABEL_2": "negatif",
    "positive": "positif",
    "neutral":  "netral",
    "negative": "negatif",
}


def analyze_text(teks: str, use_model: bool = True) -> dict:
    """
    Analisis sentimen satu teks.
    Kembalikan dict {label, score}.
    """
    if not teks or pd.isna(teks) or str(teks).strip() == "":
        return {"label": "netral", "score": 0.0}

    teks_clean = str(teks)[:512]

    if use_model:
        pipe = _get_pipeline()
        if pipe is not None:
            try:
                result = pipe(teks_clean)[0]
                label  = _LABEL_MAP.get(result["label"], "netral")
                return {"label": label, "score": round(result["score"], 4)}
            except Exception as e:
                print(f"[sentiment] Error inferensi: {e}, pakai rule-based.")

    # Fallback
    label = _rule_based_sentiment(teks_clean)
    return {"label": label, "score": 0.0}


def analyze_batch(texts: list[str], batch_size: int = 16, use_model: bool = True) -> list[dict]:
    """Analisis sentimen batch teks, tampilkan progress."""
    results = []
    pipe    = _get_pipeline() if use_model else None
    total   = len(texts)

    for i in range(0, total, batch_size):
        batch = texts[i:i + batch_size]
        batch_clean = [str(t)[:512] if t and not pd.isna(t) else "" for t in batch]

        if pipe is not None:
            try:
                raw = pipe(batch_clean)
                for r in raw:
                    label = _LABEL_MAP.get(r["label"], "netral")
                    results.append({"label": label, "score": round(r["score"], 4)})
                print(f"[sentiment]   Batch {i//batch_size + 1}/{(total-1)//batch_size + 1} selesai.")
                continue
            except Exception as e:
                print(f"[sentiment] Error batch: {e}, pakai rule-based untuk batch ini.")

        # Fallback per item
        for t in batch_clean:
            label = _rule_based_sentiment(t)
            results.append({"label": label, "score": 0.0})

    return results


def run_sentiment_analysis(use_model: bool = True) -> pd.DataFrame:
    """
    Jalankan analisis sentimen pada semua teks (tweet + berita).
    Kembalikan DataFrame dengan kolom sentimen.
    """
    frames = []

    # --- Tweet ---
    tweet_path = RAW_DIR / "tweets.csv"
    if tweet_path.exists():
        df_tweet = pd.read_csv(tweet_path)
        if "teks" in df_tweet.columns and len(df_tweet) > 0:
            print(f"[sentiment] Analisis {len(df_tweet)} tweet ...")
            results = analyze_batch(df_tweet["teks"].tolist(), use_model=use_model)
            df_tweet["sentimen"]       = [r["label"] for r in results]
            df_tweet["sentimen_score"] = [r["score"] for r in results]
            df_tweet["teks_sumber"]    = "tweet"
            frames.append(df_tweet[["tweet_id", "teks", "kategori", "lokasi_geo",
                                     "sentimen", "sentimen_score", "teks_sumber"]])

    # --- Berita ---
    news_path = RAW_DIR / "news.csv"
    if news_path.exists():
        df_news = pd.read_csv(news_path)
        if "judul" in df_news.columns and len(df_news) > 0:
            print(f"[sentiment] Analisis {len(df_news)} artikel berita ...")
            results = analyze_batch(df_news["judul"].tolist(), use_model=use_model)
            df_news["sentimen"]       = [r["label"] for r in results]
            df_news["sentimen_score"] = [r["score"] for r in results]
            df_news["teks_sumber"]    = "berita"
            df_news["tweet_id"]       = [f"news_{i}" for i in df_news.index]
            frames.append(df_news[["tweet_id", "judul", "kategori", "provinsi",
                                    "sentimen", "sentimen_score", "teks_sumber"]]
                          .rename(columns={"judul": "teks", "provinsi": "lokasi_geo"}))

    if not frames:
        print("[sentiment] Tidak ada teks untuk dianalisis.")
        return pd.DataFrame()

    df_all = pd.concat(frames, ignore_index=True)

    # Simpan CSV
    df_all.to_csv(SENTIMENT_CSV, index=False)
    print(f"[sentiment] Hasil disimpan: {SENTIMENT_CSV}")

    # Update SQLite
    if DB_PATH.exists():
        with sqlite3.connect(DB_PATH) as conn:
            df_all.to_sql("data_sentimen", conn, if_exists="replace", index=False)
        print(f"[sentiment] Tabel data_sentimen diperbarui di {DB_PATH}")

    # Ringkasan
    print("\n[sentiment] Distribusi sentimen:")
    print(df_all["sentimen"].value_counts().to_string())
    print("\n[sentiment] Sentimen per kategori:")
    print(df_all.groupby(["kategori", "sentimen"]).size().unstack(fill_value=0).to_string())

    return df_all


def get_sentimen_summary(db_path: Path = DB_PATH) -> pd.DataFrame:
    """
    Baca ringkasan sentimen dari SQLite untuk digunakan visualisasi.
    Kembalikan DataFrame [kategori, sentimen, jumlah].
    """
    if not db_path.exists():
        return pd.DataFrame()

    with sqlite3.connect(db_path) as conn:
        try:
            df = pd.read_sql(
                "SELECT kategori, sentimen, COUNT(*) as jumlah "
                "FROM data_sentimen "
                "WHERE kategori IS NOT NULL AND sentimen IS NOT NULL "
                "GROUP BY kategori, sentimen",
                conn,
            )
            return df
        except Exception:
            return pd.DataFrame()


if __name__ == "__main__":
    # Pakai rule-based dulu (use_model=False) agar tidak perlu download model saat test
    # Ganti ke use_model=True saat model sudah terinstall lengkap
    run_sentiment_analysis(use_model=False)
