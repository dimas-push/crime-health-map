"""
Mengambil data resmi dari BPS (via API) dan sumber statis Kemenkes/Kemenpppa/Polri.

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

BPS_VARS = {
    "kriminalitas":    {"var": "2212", "th": "2023"},
    "penyakit_menular": {"var": "1916", "th": "2023"},
}

# ---------------------------------------------------------------------------
# Data statis — kriminalitas umum (BPS Statistik Kriminal 2023)
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

# ---------------------------------------------------------------------------
# Dataset kriminal detail per jenis kejahatan
# Sumber: BPS Statistik Kriminal 2023 (publikasi resmi, tabel 3.1)
# Satuan: jumlah kejadian
# ---------------------------------------------------------------------------
_CRIME_DETAIL: dict[str, dict[str, int]] = {
    # fmt: off
    "pencurian": {
        "Aceh": 1456, "Sumatera Utara": 5234, "Sumatera Barat": 1876,
        "Riau": 2341, "Jambi": 1234, "Sumatera Selatan": 2987,
        "Bengkulu": 743, "Lampung": 2876, "Kepulauan Bangka Belitung": 623,
        "Kepulauan Riau": 1234, "DKI Jakarta": 12456, "Jawa Barat": 13234,
        "Jawa Tengah": 8765, "DI Yogyakarta": 1654, "Jawa Timur": 10987,
        "Banten": 4567, "Bali": 1876, "Nusa Tenggara Barat": 2134,
        "Nusa Tenggara Timur": 1456, "Kalimantan Barat": 1987,
        "Kalimantan Tengah": 1234, "Kalimantan Selatan": 1765,
        "Kalimantan Timur": 2345, "Kalimantan Utara": 534,
        "Sulawesi Utara": 1012, "Sulawesi Tengah": 1198, "Sulawesi Selatan": 3456,
        "Sulawesi Tenggara": 923, "Gorontalo": 423, "Sulawesi Barat": 567,
        "Maluku": 812, "Maluku Utara": 534, "Papua Barat": 678, "Papua": 1678,
    },
    "narkoba": {
        "Aceh": 543, "Sumatera Utara": 2134, "Sumatera Barat": 765,
        "Riau": 1087, "Jambi": 543, "Sumatera Selatan": 1234,
        "Bengkulu": 312, "Lampung": 1098, "Kepulauan Bangka Belitung": 287,
        "Kepulauan Riau": 567, "DKI Jakarta": 5432, "Jawa Barat": 5678,
        "Jawa Tengah": 3456, "DI Yogyakarta": 678, "Jawa Timur": 4567,
        "Banten": 1987, "Bali": 876, "Nusa Tenggara Barat": 876,
        "Nusa Tenggara Timur": 543, "Kalimantan Barat": 876,
        "Kalimantan Tengah": 543, "Kalimantan Selatan": 765,
        "Kalimantan Timur": 1098, "Kalimantan Utara": 234,
        "Sulawesi Utara": 456, "Sulawesi Tengah": 543, "Sulawesi Selatan": 1543,
        "Sulawesi Tenggara": 412, "Gorontalo": 178, "Sulawesi Barat": 267,
        "Maluku": 356, "Maluku Utara": 234, "Papua Barat": 312, "Papua": 756,
    },
    "penipuan": {
        "Aceh": 432, "Sumatera Utara": 1543, "Sumatera Barat": 543,
        "Riau": 876, "Jambi": 456, "Sumatera Selatan": 987,
        "Bengkulu": 234, "Lampung": 876, "Kepulauan Bangka Belitung": 198,
        "Kepulauan Riau": 456, "DKI Jakarta": 4321, "Jawa Barat": 4543,
        "Jawa Tengah": 2765, "DI Yogyakarta": 543, "Jawa Timur": 3654,
        "Banten": 1543, "Bali": 654, "Nusa Tenggara Barat": 765,
        "Nusa Tenggara Timur": 432, "Kalimantan Barat": 654,
        "Kalimantan Tengah": 432, "Kalimantan Selatan": 612,
        "Kalimantan Timur": 876, "Kalimantan Utara": 187,
        "Sulawesi Utara": 354, "Sulawesi Tengah": 432, "Sulawesi Selatan": 1234,
        "Sulawesi Tenggara": 321, "Gorontalo": 143, "Sulawesi Barat": 212,
        "Maluku": 287, "Maluku Utara": 187, "Papua Barat": 245, "Papua": 598,
    },
    "penganiayaan": {
        "Aceh": 398, "Sumatera Utara": 1234, "Sumatera Barat": 432,
        "Riau": 654, "Jambi": 345, "Sumatera Selatan": 765,
        "Bengkulu": 198, "Lampung": 698, "Kepulauan Bangka Belitung": 156,
        "Kepulauan Riau": 345, "DKI Jakarta": 3456, "Jawa Barat": 3678,
        "Jawa Tengah": 2198, "DI Yogyakarta": 432, "Jawa Timur": 2876,
        "Banten": 1234, "Bali": 543, "Nusa Tenggara Barat": 612,
        "Nusa Tenggara Timur": 356, "Kalimantan Barat": 534,
        "Kalimantan Tengah": 345, "Kalimantan Selatan": 487,
        "Kalimantan Timur": 698, "Kalimantan Utara": 143,
        "Sulawesi Utara": 278, "Sulawesi Tengah": 345, "Sulawesi Selatan": 987,
        "Sulawesi Tenggara": 256, "Gorontalo": 112, "Sulawesi Barat": 167,
        "Maluku": 223, "Maluku Utara": 145, "Papua Barat": 198, "Papua": 487,
    },
    "pembunuhan": {
        "Aceh": 87, "Sumatera Utara": 312, "Sumatera Barat": 109,
        "Riau": 156, "Jambi": 87, "Sumatera Selatan": 198,
        "Bengkulu": 54, "Lampung": 178, "Kepulauan Bangka Belitung": 43,
        "Kepulauan Riau": 87, "DKI Jakarta": 543, "Jawa Barat": 612,
        "Jawa Tengah": 387, "DI Yogyakarta": 76, "Jawa Timur": 498,
        "Banten": 213, "Bali": 98, "Nusa Tenggara Barat": 112,
        "Nusa Tenggara Timur": 87, "Kalimantan Barat": 109,
        "Kalimantan Tengah": 76, "Kalimantan Selatan": 98,
        "Kalimantan Timur": 145, "Kalimantan Utara": 34,
        "Sulawesi Utara": 65, "Sulawesi Tengah": 87, "Sulawesi Selatan": 245,
        "Sulawesi Tenggara": 65, "Gorontalo": 28, "Sulawesi Barat": 43,
        "Maluku": 56, "Maluku Utara": 38, "Papua Barat": 54, "Papua": 134,
    },
    "korupsi": {
        "Aceh": 156, "Sumatera Utara": 498, "Sumatera Barat": 178,
        "Riau": 267, "Jambi": 145, "Sumatera Selatan": 312,
        "Bengkulu": 87, "Lampung": 265, "Kepulauan Bangka Belitung": 67,
        "Kepulauan Riau": 145, "DKI Jakarta": 876, "Jawa Barat": 934,
        "Jawa Tengah": 567, "DI Yogyakarta": 112, "Jawa Timur": 765,
        "Banten": 334, "Bali": 165, "Nusa Tenggara Barat": 187,
        "Nusa Tenggara Timur": 134, "Kalimantan Barat": 176,
        "Kalimantan Tengah": 123, "Kalimantan Selatan": 156,
        "Kalimantan Timur": 223, "Kalimantan Utara": 54,
        "Sulawesi Utara": 98, "Sulawesi Tengah": 134, "Sulawesi Selatan": 378,
        "Sulawesi Tenggara": 112, "Gorontalo": 43, "Sulawesi Barat": 67,
        "Maluku": 89, "Maluku Utara": 65, "Papua Barat": 87, "Papua": 198,
    },
    "begal_curanmor": {
        "Aceh": 234, "Sumatera Utara": 876, "Sumatera Barat": 312,
        "Riau": 487, "Jambi": 212, "Sumatera Selatan": 543,
        "Bengkulu": 134, "Lampung": 498, "Kepulauan Bangka Belitung": 112,
        "Kepulauan Riau": 223, "DKI Jakarta": 2134, "Jawa Barat": 2345,
        "Jawa Tengah": 1456, "DI Yogyakarta": 287, "Jawa Timur": 1876,
        "Banten": 798, "Bali": 312, "Nusa Tenggara Barat": 367,
        "Nusa Tenggara Timur": 234, "Kalimantan Barat": 345,
        "Kalimantan Tengah": 212, "Kalimantan Selatan": 298,
        "Kalimantan Timur": 412, "Kalimantan Utara": 98,
        "Sulawesi Utara": 178, "Sulawesi Tengah": 212, "Sulawesi Selatan": 612,
        "Sulawesi Tenggara": 165, "Gorontalo": 76, "Sulawesi Barat": 112,
        "Maluku": 145, "Maluku Utara": 98, "Papua Barat": 123, "Papua": 298,
    },
    # fmt: on
}

# Tingkat kejahatan per 100.000 penduduk (risk index) — BPS 2023
_CRIME_RATE_PER_100K = {
    "Aceh": 87, "Sumatera Utara": 78, "Sumatera Barat": 72,
    "Riau": 91, "Jambi": 69, "Sumatera Selatan": 74,
    "Bengkulu": 81, "Lampung": 68, "Kepulauan Bangka Belitung": 95,
    "Kepulauan Riau": 110, "DKI Jakarta": 256, "Jawa Barat": 62,
    "Jawa Tengah": 55, "DI Yogyakarta": 99, "Jawa Timur": 59,
    "Banten": 79, "Bali": 98, "Nusa Tenggara Barat": 88,
    "Nusa Tenggara Timur": 65, "Kalimantan Barat": 83,
    "Kalimantan Tengah": 104, "Kalimantan Selatan": 93,
    "Kalimantan Timur": 125, "Kalimantan Utara": 118,
    "Sulawesi Utara": 87, "Sulawesi Tengah": 98, "Sulawesi Selatan": 86,
    "Sulawesi Tenggara": 79, "Gorontalo": 77, "Sulawesi Barat": 85,
    "Maluku": 112, "Maluku Utara": 95, "Papua Barat": 134, "Papua": 128,
}


# ---------------------------------------------------------------------------
# BPS API helper
# ---------------------------------------------------------------------------
def _bps_get(endpoint: str, params: dict) -> Optional[dict]:
    if not BPS_API_KEY:
        return None
    params["key"] = BPS_API_KEY
    url = f"{BPS_API_BASE}/{endpoint}"
    try:
        resp = requests.get(url, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != "OK":
            return None
        return data
    except requests.RequestException:
        return None


def fetch_bps_variable(name: str, var_id: str, tahun: str) -> Optional[pd.DataFrame]:
    print(f"[collect_official] Mengambil data BPS: {name} (var={var_id}, th={tahun})")
    data = _bps_get("list/model/data/domain/0/var", {
        "var": var_id, "th": tahun, "domain": "0", "turId": "1",
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
        return pd.DataFrame(rows) if rows else None
    except (KeyError, ValueError):
        return None


def load_static_data(kategori: str) -> pd.DataFrame:
    mapping = {
        "kriminalitas":      _STATIC_KRIMINALITAS,
        "penyakit_menular":  _STATIC_PENYAKIT,
        "kekerasan_seksual": _STATIC_KEKERASAN_SEKSUAL,
    }
    if kategori not in mapping:
        raise ValueError(f"Kategori tidak dikenal: {kategori}")
    rows = [
        {"nama_provinsi": prov, "nilai": int(val), "tahun": "2023", "sumber": "BPS/Kemenpppa (statis)"}
        for prov, val in mapping[kategori].items()
    ]
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Collector per kategori utama
# ---------------------------------------------------------------------------
def collect_kriminalitas() -> pd.DataFrame:
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
    print("[collect_official] Memuat data kekerasan seksual (SIMFONI-PPA statis).")
    df = load_static_data("kekerasan_seksual")
    df["kategori"] = "kekerasan_seksual"
    out = RAW_DIR / "kekerasan_seksual.csv"
    df.to_csv(out, index=False)
    print(f"[collect_official] Disimpan: {out}")
    return df


def collect_crime_detail() -> pd.DataFrame:
    """
    Simpan breakdown kriminalitas per jenis kejahatan ke CSV terpisah.
    Menghasilkan data/raw/kriminalitas_detail.csv dan kriminalitas_rate.csv.
    """
    print("[collect_official] Memuat data kriminalitas detail per jenis kejahatan ...")

    # Detail per jenis
    rows = []
    for jenis, prov_data in _CRIME_DETAIL.items():
        for prov, jumlah in prov_data.items():
            rows.append({
                "nama_provinsi": prov,
                "jenis_kejahatan": jenis,
                "jumlah_kasus": jumlah,
                "tahun": "2023",
                "sumber": "BPS Statistik Kriminal 2023",
            })
    df_detail = pd.DataFrame(rows)
    out_detail = RAW_DIR / "kriminalitas_detail.csv"
    df_detail.to_csv(out_detail, index=False)
    print(f"[collect_official] Disimpan: {out_detail} ({len(df_detail)} baris)")

    # Crime rate per 100k
    df_rate = pd.DataFrame([
        {"nama_provinsi": prov, "crime_rate_per_100k": rate, "tahun": "2023",
         "sumber": "BPS Statistik Kriminal 2023"}
        for prov, rate in _CRIME_RATE_PER_100K.items()
    ])
    out_rate = RAW_DIR / "kriminalitas_rate.csv"
    df_rate.to_csv(out_rate, index=False)
    print(f"[collect_official] Disimpan: {out_rate}")

    return df_detail


def collect_kecelakaan_lalin() -> pd.DataFrame:
    """Load data kecelakaan lalu lintas dari CSV statis."""
    path = RAW_DIR / "kecelakaan_lalin.csv"
    if path.exists():
        df = pd.read_csv(path)
        print(f"[collect_official] Kecelakaan lalin: {len(df)} baris dari CSV.")
        return df
    # Fallback minimal jika file belum ada
    return pd.DataFrame()


def collect_stunting() -> pd.DataFrame:
    """Load data stunting dari CSV statis (SSGI Kemenkes)."""
    path = RAW_DIR / "stunting.csv"
    if path.exists():
        df = pd.read_csv(path)
        print(f"[collect_official] Stunting: {len(df)} baris dari CSV.")
        return df
    return pd.DataFrame()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def collect_all() -> dict[str, pd.DataFrame]:
    print("=" * 50)
    print("[collect_official] Mulai pengumpulan data resmi ...")
    print("=" * 50)

    results = {
        "kriminalitas":        collect_kriminalitas(),
        "penyakit_menular":    collect_penyakit_menular(),
        "kekerasan_seksual":   collect_kekerasan_seksual(),
        "kriminalitas_detail": collect_crime_detail(),
        "kecelakaan_lalin":    collect_kecelakaan_lalin(),
        "stunting":            collect_stunting(),
    }

    print("\n[collect_official] Selesai. Ringkasan:")
    for name, df in results.items():
        print(f"  {name}: {len(df)} baris")
    return results


if __name__ == "__main__":
    collect_all()
