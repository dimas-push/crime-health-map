"""
Pipeline runner — jalankan seluruh proses dari awal hingga generate peta.

Usage:
    python run_all.py              # jalankan semua tahap
    python run_all.py --skip-collect   # lewati pengumpulan data (pakai cache)
    python run_all.py --use-model      # aktifkan IndoBERT (butuh GPU/RAM besar)
    python run_all.py --force          # hapus cache & mulai dari awal
"""

import argparse
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "src"))

from collect_official import collect_all as collect_official
from collect_news     import collect_news
from collect_social   import collect_social
from process          import process_all
from sentiment        import run_sentiment_analysis

PROCESSED_DIR = ROOT / "data" / "processed"
GEOJSON_DIR   = ROOT / "data" / "geojson"


def _banner(msg: str) -> None:
    print(f"\n{'='*55}")
    print(f"  {msg}")
    print(f"{'='*55}")


def _elapsed(start: float) -> str:
    secs = int(time.time() - start)
    return f"{secs//60}m {secs%60}s"


def main() -> None:
    parser = argparse.ArgumentParser(description="Crime & Health Map — Pipeline Runner")
    parser.add_argument("--skip-collect", action="store_true",
                        help="Lewati tahap pengumpulan data, pakai data yang sudah ada")
    parser.add_argument("--use-model",    action="store_true",
                        help="Gunakan IndoBERT untuk analisis sentimen (butuh ~2GB RAM)")
    parser.add_argument("--force",        action="store_true",
                        help="Hapus semua cache dan mulai dari awal")
    args = parser.parse_args()

    total_start = time.time()

    # Hapus cache jika --force
    if args.force:
        _banner("FORCE MODE: Menghapus cache ...")
        for path in [PROCESSED_DIR, GEOJSON_DIR]:
            if path.exists():
                shutil.rmtree(path)
                print(f"  Dihapus: {path}")

    # ── TAHAP 1-3: Kumpulkan data ───────────────────────────────────────────
    if not args.skip_collect:
        _banner("TAHAP 1/5 — Pengumpulan Data Resmi")
        t = time.time()
        collect_official()
        print(f"  Selesai dalam {_elapsed(t)}")

        _banner("TAHAP 2/5 — Scraping Berita")
        t = time.time()
        collect_news()
        print(f"  Selesai dalam {_elapsed(t)}")

        _banner("TAHAP 3/5 — Data Sosial Media")
        t = time.time()
        collect_social()
        print(f"  Selesai dalam {_elapsed(t)}")
    else:
        print("\n[run_all] --skip-collect: lewati tahap pengumpulan data.")

    # ── TAHAP 4: Proses & simpan ke SQLite ──────────────────────────────────
    _banner("TAHAP 4/5 — Pemrosesan & Database")
    t = time.time()
    # Hapus cache final.csv agar proses rebuild dengan data terbaru
    final_csv = PROCESSED_DIR / "final.csv"
    if final_csv.exists():
        final_csv.unlink()
    process_all()
    print(f"  Selesai dalam {_elapsed(t)}")

    # ── TAHAP 5: Analisis sentimen ──────────────────────────────────────────
    _banner("TAHAP 5/5 — Analisis Sentimen")
    t = time.time()
    run_sentiment_analysis(use_model=args.use_model)
    print(f"  Selesai dalam {_elapsed(t)}")

    # ── TAHAP 4: Generate peta ──────────────────────────────────────────────
    _banner("GENERATE PETA")
    t = time.time()
    import subprocess
    result = subprocess.run(
        [sys.executable, str(ROOT / "generate_map.py")],
        capture_output=False,
    )
    if result.returncode != 0:
        print("[run_all] ERROR: generate_map.py gagal.")
        sys.exit(1)
    print(f"  Selesai dalam {_elapsed(t)}")

    _banner(f"PIPELINE SELESAI — Total waktu: {_elapsed(total_start)}")
    print("  File output:")
    print(f"    Peta  : {ROOT / 'docs' / 'index.html'}")
    print(f"    DB    : {PROCESSED_DIR / 'crime_health.db'}")
    print(f"    CSV   : {PROCESSED_DIR / 'final.csv'}")
    print()


if __name__ == "__main__":
    main()
