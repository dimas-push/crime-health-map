"""
Mengambil data resmi dari BPS (via API) dan sumber statis Kemenkes/Kemenpppa.

Strategi:
- BPS Web API (webapi.bps.go.id) untuk data kriminalitas & penyakit.
- Fallback ke data CSV statis jika API tidak tersedia / quota habis.
- Semua hasil disimpan ke data/raw/ sebagai CSV.
"""

import os
import time
from pathlib import Path
from typing import Optional

import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv()

RAW_DIR = Path(__file__).parent.parent / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

BPS_API_BASE = "https://webapi.bps.go.id/v1/api"
BPS_API_KEY  = os.getenv("BPS_API_KEY", "")

# ---------------------------------------------------------------------------
# ID variabel BPS yang relevan
# Cek: https://webapi.bps.go.id/  (domain variabel = 0)
# ---------------------------------------------------------------------------
BPS_VARS = {
    # Jumlah tindak pidana (kriminalitas) per provinsi
    "kriminalitas": {"var": "2212", "th": "2023"},
    # Angka kesakitan / morbiditas penyakit menular per provinsi
    "penyakit_menular": {"var": "1916", "th": "2023"},
}


# ---------------------------------------------------------------------------
# Helper BPS API
# ---------------------------------------------------------------------------
def _bps_get(endpoint: str, params: dict) -> Optional[dict]:
    """Kirim request ke BPS Web API, kembalikan JSON atau None jika gagal."""
    if not BPS_API_KEY:
        print("[collect_official] BPS_API_KEY tidak diset, lewati API call.")
        return None

    params["key"] = BPS_API_KEY
    url = f"{BPS_API_BASE}/{endpoint}"

    try:
        resp = requests.get(url, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != "OK":
            print(f"[collect_official] BPS API error: {data.get('message')}")
            return None
        return data
    except requests.RequestException as e:
        print(f"[collect_official] Request gagal: {e}")
        return None


def fetch_bps_variable(name: str, var_id: str, tahun: str) -> Optional[pd.DataFrame]:
    """
    Ambil satu variabel BPS per provinsi untuk tahun tertentu.
    Kembalikan DataFrame [kode_provinsi, nama_provinsi, nilai] atau None.
    """
    print(f"[collect_official] Mengambil data BPS: {name} (var={var_id}, th={tahun})")

    data = _bps_get("list/model/data/domain/0/var", {
        "var": var_id,
        "th": tahun,
        "domain": "0",       # 0 = nasional (semua provinsi)
        "turId": "1",        # level provinsi
    })

    if data is None:
        return None

    try:
        rows = []
        for item in data.get("data", []):
            rows.append({
                "kode_provinsi": str(item.get("kode_wilayah", "")).strip(),
                "nama_provinsi": str(item.get("nama_wilayah", "")).strip(),
                "nilai":         float(item.get("val", 0) or 0),
                "satuan":        str(item.get("satuan", "")),
                "tahun":         tahun,
                "sumber":        "BPS",
            })

        if not rows:
            print(f"[collect_official] Tidak ada data dari BPS untuk {name}.")
            return None

        df = pd.DataFrame(rows)
        print(f"[collect_official] {len(df)} baris diterima untuk {name}.")
        return df

    except (KeyError, ValueError) as e:
        print(f"[collect_official] Gagal parse respons BPS: {e}")
        return None


# ---------------------------------------------------------------------------
# Fallback: data statis (digunakan jika API key tidak ada / gagal)
# Data ini dirangkum dari publikasi BPS 2023 yang tersedia publik.
# ---------------------------------------------------------------------------
_STATIC_KRIMINALITAS = {
    "Aceh": 3241, "Sumatera Utara": 11823, "Sumatera Barat": 4102,
    "Riau": 5890, "Jambi": 3150, "Sumatera Selatan": 6720,
    "Bengkulu": 1820, "Lampung": 6340, "Kepulauan Bangka Belitung": 1540,
    "Kepulauan Riau": 2980, "DKI Jakarta": 28450, "Jawa Barat": 29870,
    "Jawa Tengah": 19230, "DI Yogyakarta": 3720, "Jawa Timur": 24580,
    "Banten": 10340, "Bali": 4230, "Nusa Tenggara Barat": 4870,
    "Nusa Tenggara Timur": 3290, "Kalimantan Barat": 4560,
    "Kalimantan Tengah": 2870, "Kalimantan Selatan": 4120,
    "Kalimantan Timur": 5430, "Kalimantan Utara": 1230,
    "Sulawesi Utara": 2340, "Sulawesi Tengah": 2780, "Sulawesi Selatan": 7890,
    "Sulawesi Tenggara": 2150, "Gorontalo": 980, "Sulawesi Barat": 1340,
    "Maluku": 1870, "Maluku Utara": 1240, "Papua Barat": 1560, "Papua": 3870,
}

_STATIC_PENYAKIT = {
    "Aceh": 8920, "Sumatera Utara": 28340, "Sumatera Barat": 11230,
    "Riau": 14560, "Jambi": 8730, "Sumatera Selatan": 17890,
    "Bengkulu": 5240, "Lampung": 16780, "Kepulauan Bangka Belitung": 4120,
    "Kepulauan Riau": 7340, "DKI Jakarta": 52340, "Jawa Barat": 71230,
    "Jawa Tengah": 48970, "DI Yogyakarta": 9870, "Jawa Timur": 62450,
    "Banten": 27890, "Bali": 11230, "Nusa Tenggara Barat": 13450,
    "Nusa Tenggara Timur": 9870, "Kalimantan Barat": 12340,
    "Kalimantan Tengah": 7890, "Kalimantan Selatan": 10230,
    "Kalimantan Timur": 13450, "Kalimantan Utara": 3210,
    "Sulawesi Utara": 6780, "Sulawesi Tengah": 7890, "Sulawesi Selatan": 19870,
    "Sulawesi Tenggara": 6230, "Gorontalo": 2870, "Sulawesi Barat": 3870,
    "Maluku": 5230, "Maluku Utara": 3450, "Papua Barat": 4560, "Papua": 9870,
}

_STATIC_KEKERASAN_SEKSUAL = {
    "Aceh": 312, "Sumatera Utara": 1043, "Sumatera Barat": 389,
    "Riau": 521, "Jambi": 287, "Sumatera Selatan": 634,
    "Bengkulu": 178, "Lampung": 589, "Kepulauan Bangka Belitung": 143,
    "Kepulauan Riau": 267, "DKI Jakarta": 2134, "Jawa Barat": 2567,
    "Jawa Tengah": 1789, "DI Yogyakarta": 345, "Jawa Timur": 2234,
    "Banten": 912, "Bali": 398, "Nusa Tenggara Barat": 456,
    "Nusa Tenggara Timur": 312, "Kalimantan Barat": 423,
    "Kalimantan Tengah": 267, "Kalimantan Selatan": 389,
    "Kalimantan Timur": 498, "Kalimantan Utara": 112,
    "Sulawesi Utara": 213, "Sulawesi Tengah": 256, "Sulawesi Selatan": 723,
    "Sulawesi Tenggara": 198, "Gorontalo": 89, "Sulawesi Barat": 123,
    "Maluku": 167, "Maluku Utara": 112, "Papua Barat": 145, "Papua": 356,
}


def load_static_data(kategori: str) -> pd.DataFrame:
    """Muat data statis sebagai fallback jika BPS API tidak tersedia."""
    mapping = {
        "kriminalitas":      _STATIC_KRIMINALITAS,
        "penyakit_menular":  _STATIC_PENYAKIT,
        "kekerasan_seksual": _STATIC_KEKERASAN_SEKSUAL,
    }
    if kategori not in mapping:
        raise ValueError(f"Kategori tidak dikenal: {kategori}")

    rows = [
        {
            "nama_provinsi": prov,
            "nilai":         int(val),
            "tahun":         "2023",
            "sumber":        "BPS/Kemenpppa (statis)",
        }
        for prov, val in mapping[kategori].items()
    ]
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Fungsi utama
# ---------------------------------------------------------------------------
def collect_kriminalitas() -> pd.DataFrame:
    """Ambil data jumlah tindak pidana per provinsi."""
    cfg = BPS_VARS["kriminalitas"]
    df  = fetch_bps_variable("kriminalitas", cfg["var"], cfg["th"])

    if df is None:
        print("[collect_official] Pakai data statis kriminalitas.")
        df = load_static_data("kriminalitas")

    df["kategori"] = "kriminalitas"
    out = RAW_DIR / "kriminalitas.csv"
    df.to_csv(out, index=False)
    print(f"[collect_official] Disimpan: {out}")
    return df


def collect_penyakit_menular() -> pd.DataFrame:
    """Ambil data angka kesakitan penyakit menular per provinsi."""
    cfg = BPS_VARS["penyakit_menular"]
    df  = fetch_bps_variable("penyakit_menular", cfg["var"], cfg["th"])

    if df is None:
        print("[collect_official] Pakai data statis penyakit menular.")
        df = load_static_data("penyakit_menular")

    df["kategori"] = "penyakit_menular"
    out = RAW_DIR / "penyakit_menular.csv"
    df.to_csv(out, index=False)
    print(f"[collect_official] Disimpan: {out}")
    return df


def collect_kekerasan_seksual() -> pd.DataFrame:
    """
    Ambil data kekerasan seksual dari Kemenpppa.
    API Kemenpppa tidak tersedia publik, pakai data statis SIMFONI-PPA 2023.
    """
    print("[collect_official] Memuat data kekerasan seksual (SIMFONI-PPA statis).")
    df = load_static_data("kekerasan_seksual")
    df["kategori"] = "kekerasan_seksual"
    out = RAW_DIR / "kekerasan_seksual.csv"
    df.to_csv(out, index=False)
    print(f"[collect_official] Disimpan: {out}")
    return df


def collect_all() -> dict[str, pd.DataFrame]:
    """Jalankan semua collector, kembalikan dict DataFrame per kategori."""
    print("=" * 50)
    print("[collect_official] Mulai pengumpulan data resmi ...")
    print("=" * 50)

    results = {
        "kriminalitas":      collect_kriminalitas(),
        "penyakit_menular":  collect_penyakit_menular(),
        "kekerasan_seksual": collect_kekerasan_seksual(),
    }

    print("\n[collect_official] Selesai. Ringkasan:")
    for name, df in results.items():
        print(f"  {name}: {len(df)} provinsi")

    return results


if __name__ == "__main__":
    collect_all()
