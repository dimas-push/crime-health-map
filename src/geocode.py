"""
Geocoding kabupaten/kota Indonesia → koordinat lat/lon.

Strategi:
1. Kamus statis 514 kabupaten/kota (dari data BPS, tidak perlu API).
2. Fallback ke Nominatim (OpenStreetMap) untuk nama yang tidak ada di kamus.
3. Hasil Nominatim di-cache ke data/processed/geocode_cache.json.
"""

import json
import time
from pathlib import Path
from typing import Optional

import requests

CACHE_PATH = Path(__file__).parent.parent / "data" / "processed" / "geocode_cache.json"

# ---------------------------------------------------------------------------
# Kamus statis — ibukota / titik tengah tiap kabupaten/kota
# Format: "nama_kabupaten_lowercase": (lat, lon)
# ---------------------------------------------------------------------------
_COORDS: dict[str, tuple[float, float]] = {
    # ── ACEH ──
    "kota banda aceh": (5.5577, 95.3222), "aceh besar": (5.4737, 95.6125),
    "pidie": (4.9619, 96.1167), "bireuen": (5.2036, 96.6962),
    "aceh utara": (4.9636, 97.0993), "lhokseumawe": (5.1801, 97.1503),
    "aceh timur": (4.6475, 97.7745), "langsa": (4.4782, 97.9681),
    "aceh tamiang": (4.2918, 98.1847), "gayo lues": (3.8273, 97.0997),
    "aceh tengah": (4.6063, 96.7969), "bener meriah": (4.7191, 96.8695),
    "aceh barat": (4.0955, 96.1285), "nagan raya": (3.8957, 96.0744),
    "aceh barat daya": (3.4287, 96.9303), "aceh selatan": (3.0285, 97.4012),
    "aceh singkil": (2.3285, 97.7924), "subulussalam": (2.6397, 98.0022),
    "simeulue": (2.6271, 96.1027), "sabang": (5.8931, 95.3194),
    "pidie jaya": (5.1697, 96.1897),
    # ── SUMATERA UTARA ──
    "kota medan": (3.5952, 98.6722), "kota binjai": (3.6000, 98.4833),
    "kota tebing tinggi": (3.3286, 99.1628), "kota pematangsiantar": (2.9593, 99.0687),
    "kota tanjungbalai": (2.9667, 99.8000), "kota sibolga": (1.7427, 98.7792),
    "kota padangsidimpuan": (1.3667, 99.2667), "kota gunungsitoli": (1.2880, 97.6095),
    "deli serdang": (3.4966, 98.7765), "langkat": (3.9922, 98.2095),
    "serdang bedagai": (3.3044, 98.9717), "karo": (3.1333, 98.4833),
    "dairi": (2.7833, 98.3333), "pakpak bharat": (2.4504, 98.2282),
    "samosir": (2.6000, 98.8500), "toba samosir": (2.3748, 99.0940),
    "humbang hasundutan": (2.2067, 98.7589), "tapanuli utara": (2.0833, 99.0000),
    "tapanuli tengah": (1.6760, 98.6960), "tapanuli selatan": (1.4167, 99.3000),
    "padang lawas utara": (1.5167, 99.8500), "padang lawas": (1.3796, 99.7921),
    "mandailing natal": (0.9000, 99.3667), "nias": (1.0880, 97.7555),
    "nias selatan": (0.5256, 97.8700), "nias barat": (1.2497, 97.4900),
    "nias utara": (1.4263, 97.5672), "batubara": (2.9997, 99.5000),
    "asahan": (2.9869, 99.8575), "labuhanbatu": (2.2000, 100.1167),
    "labuhanbatu selatan": (1.8467, 100.2900), "labuhanbatu utara": (2.5544, 100.0035),
    # ── SUMATERA BARAT ──
    "kota padang": (-0.9471, 100.4172), "kota bukittinggi": (-0.3060, 100.3691),
    "kota payakumbuh": (-0.2256, 100.6275), "kota solok": (-0.7999, 100.6557),
    "kota sawahlunto": (-0.6833, 100.7833), "kota padangpanjang": (-0.4667, 100.4167),
    "kota pariaman": (-0.6264, 100.1199), "agam": (-0.2167, 100.0667),
    "tanah datar": (-0.4531, 100.5746), "50 kota": (-0.1500, 100.6000),
    "pasaman": (0.4500, 99.8333), "pasaman barat": (0.0833, 99.7167),
    "padang pariaman": (-0.5333, 100.1167), "pesisir selatan": (-2.0000, 100.7167),
    "solok": (-1.0500, 100.7000), "solok selatan": (-1.8667, 100.9167),
    "sijunjung": (-0.6833, 100.9667), "dharmasraya": (-1.2000, 101.5333),
    "kepulauan mentawai": (-1.7900, 99.4900),
    # ── RIAU ──
    "kota pekanbaru": (0.5333, 101.4500), "kota dumai": (1.6667, 101.4500),
    "kampar": (0.3500, 101.1500), "rokan hulu": (1.0667, 100.5000),
    "rokan hilir": (2.1167, 100.9167), "bengkalis": (1.4833, 102.1000),
    "kepulauan meranti": (1.1910, 102.7515), "siak": (1.2000, 102.0000),
    "pelalawan": (0.0000, 102.0000), "indragiri hulu": (-0.3333, 102.5000),
    "indragiri hilir": (-0.5000, 103.2500), "kuantan singingi": (-0.2000, 101.5333),
    # ── KEPULAUAN RIAU ──
    "kota tanjungpinang": (0.9167, 104.4500), "kota batam": (1.1167, 104.0000),
    "bintan": (1.1333, 104.5000), "karimun": (1.0167, 103.3667),
    "natuna": (3.9500, 108.3833), "lingga": (-0.2000, 104.6167),
    "kepulauan anambas": (3.3167, 106.1333),
    # ── JAMBI ──
    "kota jambi": (-1.6167, 103.6167), "batanghari": (-1.6667, 103.0000),
    "muaro jambi": (-1.7667, 103.7833), "tanjung jabung timur": (-1.0833, 103.7833),
    "tanjung jabung barat": (-1.1333, 103.5000), "tebo": (-1.5000, 102.1500),
    "bungo": (-1.5000, 102.0000), "merangin": (-2.3500, 102.0833),
    "sarolangun": (-2.3667, 102.7833), "kerinci": (-2.0833, 101.6167),
    "kota sungaipenuh": (-2.0667, 101.3833),
    # ── SUMATERA SELATAN ──
    "kota palembang": (-2.9167, 104.7458), "kota prabumulih": (-3.4364, 104.2408),
    "kota pagar alam": (-4.0167, 103.2667), "kota lubuklinggau": (-3.2833, 102.8667),
    "ogan komering ulu": (-4.3333, 104.1667), "ogan komering ilir": (-3.5000, 105.0000),
    "muara enim": (-3.5833, 103.7833), "lahat": (-3.7833, 103.5333),
    "musi rawas": (-3.0000, 103.0000), "musi banyuasin": (-2.7500, 103.7500),
    "banyuasin": (-2.7500, 104.7500), "ogan ilir": (-3.3333, 104.6667),
    "empat lawang": (-3.6500, 103.1500), "penukal abab lematang ilir": (-3.9167, 103.8667),
    "musi rawas utara": (-2.6000, 103.0000),
    # ── BENGKULU ──
    "kota bengkulu": (-3.8000, 102.2667), "bengkulu utara": (-3.1667, 101.9833),
    "mukomuko": (-2.5333, 101.1167), "bengkulu tengah": (-3.7167, 102.2333),
    "kepahiang": (-3.6333, 102.6000), "rejang lebong": (-3.4667, 102.5500),
    "lebong": (-3.0333, 102.3333), "bengkulu selatan": (-4.4667, 102.6167),
    "kaur": (-4.5500, 103.4500), "seluma": (-4.0500, 102.4833),
    # ── LAMPUNG ──
    "kota bandar lampung": (-5.4292, 105.2611), "kota metro": (-5.1167, 105.3167),
    "lampung barat": (-5.1167, 104.0833), "pesisir barat": (-5.2833, 103.7667),
    "tanggamus": (-5.5000, 104.6167), "pringsewu": (-5.3500, 104.9833),
    "pesawaran": (-5.4500, 105.1500), "lampung selatan": (-5.5833, 105.5000),
    "lampung timur": (-5.2833, 105.7000), "lampung tengah": (-4.8167, 105.2500),
    "lampung utara": (-4.7833, 104.9167), "way kanan": (-4.4167, 104.4500),
    "tulang bawang barat": (-4.5167, 105.1167), "tulang bawang": (-4.1667, 105.6667),
    "mesuji": (-3.8333, 105.5000),
    # ── KEPULAUAN BANGKA BELITUNG ──
    "kota pangkalpinang": (-2.1167, 106.1167), "bangka": (-2.2167, 106.0667),
    "bangka barat": (-1.8167, 105.7000), "bangka tengah": (-2.3500, 106.0167),
    "bangka selatan": (-3.0667, 106.4500), "belitung": (-2.8167, 107.6167),
    "belitung timur": (-2.7167, 108.1833),
    # ── DKI JAKARTA ──
    "jakarta pusat": (-6.1862, 106.8063), "jakarta utara": (-6.1381, 106.8451),
    "jakarta barat": (-6.1682, 106.7592), "jakarta selatan": (-6.2615, 106.8106),
    "jakarta timur": (-6.2250, 106.9004), "kepulauan seribu": (-5.7374, 106.6153),
    # ── JAWA BARAT ──
    "kota bandung": (-6.9175, 107.6191), "kota bekasi": (-6.2349, 106.9896),
    "kota depok": (-6.4025, 106.7942), "kota bogor": (-6.5971, 106.8060),
    "kota sukabumi": (-6.9255, 106.9297), "kota cirebon": (-6.7064, 108.5574),
    "kota tasikmalaya": (-7.3274, 108.2207), "kota banjar": (-7.3709, 108.5299),
    "kota cimahi": (-6.8721, 107.5427),
    "karawang": (-6.3028, 107.3042), "bekasi": (-6.3748, 107.1249),
    "bogor": (-6.5971, 106.8060), "sukabumi": (-7.0000, 106.9000),
    "cianjur": (-6.8196, 107.1419), "bandung": (-6.9039, 107.6186),
    "bandung barat": (-6.8369, 107.4456), "sumedang": (-6.8547, 107.9180),
    "garut": (-7.2269, 107.9069), "tasikmalaya": (-7.2167, 108.1833),
    "ciamis": (-7.3288, 108.3535), "kuningan": (-6.9757, 108.4875),
    "cirebon": (-6.7414, 108.4825), "majalengka": (-6.8310, 108.2266),
    "indramayu": (-6.3275, 108.3197), "subang": (-6.5738, 107.7606),
    "purwakarta": (-6.5578, 107.4430), "pangandaran": (-7.6897, 108.6509),
    # ── JAWA TENGAH ──
    "kota semarang": (-6.9932, 110.4203), "kota surakarta": (-7.5755, 110.8243),
    "kota magelang": (-7.4797, 110.2177), "kota salatiga": (-7.3306, 110.5082),
    "kota pekalongan": (-6.8883, 109.6753), "kota tegal": (-6.8694, 109.1402),
    "cilacap": (-7.7297, 109.0153), "banyumas": (-7.5153, 109.2942),
    "purbalingga": (-7.3881, 109.3617), "banjarnegara": (-7.3853, 109.6930),
    "kebumen": (-7.6667, 109.6500), "purworejo": (-7.7167, 110.0167),
    "wonosobo": (-7.3667, 109.9000), "magelang": (-7.4667, 110.2167),
    "boyolali": (-7.5333, 110.5833), "klaten": (-7.7043, 110.6085),
    "sukoharjo": (-7.6833, 110.8333), "wonogiri": (-7.8167, 110.9167),
    "karanganyar": (-7.6000, 111.0333), "sragen": (-7.4333, 111.0167),
    "grobogan": (-7.0000, 110.8833), "blora": (-6.9667, 111.4167),
    "rembang": (-6.7037, 111.3430), "pati": (-6.7500, 111.0333),
    "kudus": (-6.8049, 110.8367), "jepara": (-6.5873, 110.6680),
    "demak": (-6.8944, 110.6381), "semarang": (-7.0333, 110.5000),
    "kendal": (-6.9167, 110.2000), "batang": (-6.9167, 109.7333),
    "pekalongan": (-6.9833, 109.6833), "pemalang": (-6.8833, 109.3833),
    "tegal": (-6.8783, 109.1249), "brebes": (-6.8717, 109.0381),
    "temanggung": (-7.3167, 110.1833),
    # ── DI YOGYAKARTA ──
    "kota yogyakarta": (-7.7956, 110.3695), "sleman": (-7.7167, 110.3667),
    "bantul": (-7.8833, 110.3333), "kulon progo": (-7.8333, 110.1667),
    "gunungkidul": (-7.9833, 110.5833),
    # ── JAWA TIMUR ──
    "kota surabaya": (-7.2575, 112.7521), "kota malang": (-7.9839, 112.6214),
    "kota kediri": (-7.8167, 112.0167), "kota blitar": (-8.0961, 112.1608),
    "kota madiun": (-7.6298, 111.5228), "kota mojokerto": (-7.4724, 112.4338),
    "kota pasuruan": (-7.6467, 112.9073), "kota probolinggo": (-7.7544, 113.2192),
    "kota batu": (-7.8688, 112.5268),
    "gresik": (-7.1569, 112.6547), "sidoarjo": (-7.4478, 112.7183),
    "mojokerto": (-7.4667, 112.4333), "jombang": (-7.5500, 112.2333),
    "nganjuk": (-7.6000, 111.9167), "madiun": (-7.6333, 111.5167),
    "magetan": (-7.6500, 111.3333), "ngawi": (-7.4167, 111.4167),
    "bojonegoro": (-7.1500, 111.8833), "tuban": (-6.9000, 112.0500),
    "lamongan": (-7.1167, 112.4167), "kediri": (-7.8167, 112.0167),
    "tulungagung": (-8.0667, 111.9000), "blitar": (-8.0961, 112.1608),
    "malang": (-8.1578, 112.6269), "lumajang": (-8.1500, 113.2167),
    "pasuruan": (-7.6333, 112.9000), "probolinggo": (-7.7500, 113.2167),
    "situbondo": (-7.7000, 114.0000), "bondowoso": (-7.9167, 113.8167),
    "jember": (-8.1725, 113.7000), "banyuwangi": (-8.2192, 114.3692),
    "bangkalan": (-6.9000, 113.0667), "sampang": (-7.1833, 113.2500),
    "pamekasan": (-7.1500, 113.4667), "sumenep": (-6.9833, 113.8667),
    "trenggalek": (-8.0500, 111.7000), "pacitan": (-8.2000, 111.1000),
    "ponorogo": (-7.8667, 111.4667),
    # ── BANTEN ──
    "kota serang": (-6.1204, 106.1502), "kota tangerang": (-6.1784, 106.6319),
    "kota tangerang selatan": (-6.2898, 106.7093), "kota cilegon": (-6.0027, 106.0025),
    "serang": (-6.1204, 106.1502), "tangerang": (-6.1784, 106.6319),
    "lebak": (-6.5606, 106.2492), "pandeglang": (-6.3083, 106.1083),
    # ── BALI ──
    "kota denpasar": (-8.6705, 115.2126), "badung": (-8.5506, 115.1864),
    "gianyar": (-8.5372, 115.3319), "tabanan": (-8.5358, 115.0850),
    "jembrana": (-8.3594, 114.6211), "buleleng": (-8.1083, 115.0908),
    "bangli": (-8.4561, 115.3558), "karangasem": (-8.4458, 115.6122),
    "klungkung": (-8.5383, 115.4031),
    # ── NUSA TENGGARA BARAT ──
    "kota mataram": (-8.5833, 116.1167), "kota bima": (-8.4573, 118.7250),
    "lombok barat": (-8.6500, 116.0833), "lombok tengah": (-8.7000, 116.3333),
    "lombok timur": (-8.6167, 116.5833), "lombok utara": (-8.3625, 116.1208),
    "sumbawa": (-8.4892, 117.4181), "sumbawa barat": (-8.7833, 116.9167),
    "dompu": (-8.5333, 118.4667), "bima": (-8.5000, 118.7167),
    # ── NUSA TENGGARA TIMUR ──
    "kota kupang": (-10.1718, 123.6070), "kupang": (-10.0000, 124.0000),
    "timor tengah selatan": (-9.8667, 124.3667), "timor tengah utara": (-9.3667, 124.8000),
    "belu": (-9.4833, 125.2167), "alor": (-8.2167, 124.5167),
    "lembata": (-8.4167, 123.5000), "flores timur": (-8.2167, 122.9167),
    "sikka": (-8.5333, 122.2667), "ende": (-8.8500, 121.6667),
    "ngada": (-8.6500, 121.0500), "nagekeo": (-8.7500, 121.1833),
    "manggarai": (-8.6333, 120.4500), "manggarai barat": (-8.5000, 119.8833),
    "manggarai timur": (-8.7167, 120.8833), "rote ndao": (-10.6833, 123.0500),
    "sabu raijua": (-10.4833, 121.8167), "malaka": (-9.5667, 124.8333),
    "sumba timur": (-9.6667, 120.2667), "sumba tengah": (-9.8333, 119.7833),
    "sumba barat": (-9.6667, 119.3167), "sumba barat daya": (-9.5833, 118.9500),
    # ── KALIMANTAN BARAT ──
    "kota pontianak": (-0.0333, 109.3333), "kota singkawang": (0.9000, 108.9833),
    "mempawah": (0.2833, 108.9833), "sambas": (1.3667, 109.3000),
    "bengkayang": (0.8000, 109.6833), "landak": (0.3833, 110.1167),
    "sanggau": (0.1167, 110.5833), "sekadau": (-0.0167, 110.9500),
    "melawi": (-0.0667, 111.5333), "sintang": (-0.0667, 111.5000),
    "kapuas hulu": (0.8667, 113.0000), "kayong utara": (-1.2000, 110.0167),
    "ketapang": (-1.8333, 110.0000), "kubu raya": (-0.2000, 109.3667),
    # ── KALIMANTAN TENGAH ──
    "kota palangka raya": (-2.2167, 113.9167), "kotawaringin barat": (-2.7500, 111.6833),
    "kotawaringin timur": (-2.3333, 112.9833), "kapuas": (-2.8833, 114.0000),
    "barito selatan": (-2.0000, 114.8333), "barito utara": (-0.9333, 114.8333),
    "barito timur": (-1.8667, 115.5000), "murung raya": (-0.8333, 114.9333),
    "seruyan": (-2.8833, 112.5667), "katingan": (-1.7000, 113.0000),
    "pulang pisau": (-2.8833, 113.8833), "gunung mas": (-1.6667, 113.8833),
    "lamandau": (-2.1667, 111.5667), "sukamara": (-2.6833, 111.0833),
    # ── KALIMANTAN SELATAN ──
    "kota banjarmasin": (-3.3167, 114.5833), "kota banjarbaru": (-3.4333, 114.8333),
    "banjar": (-3.3667, 115.0000), "tanah laut": (-3.8500, 114.9833),
    "tanah bumbu": (-3.5667, 115.8167), "kotabaru": (-3.3167, 116.2333),
    "tapin": (-2.9667, 115.0000), "hulu sungai selatan": (-2.6833, 115.4167),
    "hulu sungai tengah": (-2.3667, 115.5000), "hulu sungai utara": (-2.0833, 115.2167),
    "balangan": (-2.2833, 115.3667), "tabalong": (-2.0333, 115.6000),
    "barito kuala": (-2.9833, 114.8333),
    # ── KALIMANTAN TIMUR ──
    "kota samarinda": (-0.4936, 117.1436), "kota balikpapan": (-1.2654, 116.8312),
    "kota bontang": (0.1333, 117.5000), "kutai kartanegara": (-0.4500, 117.0000),
    "kutai barat": (-0.9167, 115.5833), "kutai timur": (1.4500, 117.5000),
    "berau": (2.1667, 117.5000), "penajam paser utara": (-1.2667, 116.5000),
    "paser": (-1.8333, 115.8333), "mahakam ulu": (0.3333, 115.5000),
    # ── KALIMANTAN UTARA ──
    "kota tarakan": (3.3167, 117.5833), "bulungan": (2.6833, 117.3667),
    "kota tanjung selor": (2.8370, 117.3640),
    "malinau": (3.5833, 116.6167), "nunukan": (4.1333, 117.6667),
    "tana tidung": (3.5333, 117.2500),
    # ── SULAWESI UTARA ──
    "kota manado": (1.4931, 124.8413), "kota bitung": (1.4500, 125.2000),
    "kota tomohon": (1.3167, 124.8333), "kota kotamobagu": (0.7333, 124.3167),
    "minahasa": (1.2167, 124.8333), "minahasa utara": (1.6500, 124.9000),
    "minahasa selatan": (0.9833, 124.5833), "minahasa tenggara": (0.7667, 124.5667),
    "kepulauan sangihe": (3.5667, 125.5167), "kepulauan talaud": (4.2500, 126.7500),
    "kepulauan sitaro": (2.7000, 125.3833), "bolaang mongondow": (0.5833, 124.1500),
    "bolaang mongondow utara": (1.1333, 124.1500), "bolaang mongondow timur": (0.5000, 124.4167),
    "bolaang mongondow selatan": (0.2000, 123.8500),
    # ── SULAWESI TENGAH ──
    "kota palu": (-0.9000, 119.8667), "donggala": (-0.6667, 119.7500),
    "sigi": (-1.2000, 119.9167), "parigi moutong": (-0.4500, 120.1667),
    "poso": (-1.5000, 120.7500), "morowali": (-2.5000, 121.9167),
    "morowali utara": (-1.7500, 121.6667), "tojo una-una": (-0.6000, 121.6667),
    "banggai": (-1.5000, 122.7500), "banggai kepulauan": (-1.8333, 123.5000),
    "banggai laut": (-1.6167, 123.4833), "buol": (1.2000, 121.4000),
    "tolitoli": (1.0500, 120.8167),
    # ── SULAWESI SELATAN ──
    "kota makassar": (-5.1477, 119.4327), "kota parepare": (-4.0167, 119.6333),
    "kota palopo": (-3.0000, 120.1833),
    "gowa": (-5.2833, 119.6000), "takalar": (-5.4500, 119.3833),
    "jeneponto": (-5.6833, 119.6833), "bantaeng": (-5.5167, 119.9333),
    "bulukumba": (-5.5667, 120.2167), "sinjai": (-5.1167, 120.2500),
    "bone": (-4.7333, 120.3167), "soppeng": (-4.3500, 119.8833),
    "wajo": (-3.9833, 120.2167), "sidrap": (-3.9167, 119.8333),
    "pinrang": (-3.7833, 119.6333), "enrekang": (-3.5167, 119.7833),
    "tana toraja": (-3.0500, 119.8667), "toraja utara": (-2.9667, 119.9000),
    "luwu": (-2.8833, 120.6833), "luwu utara": (-2.4333, 120.6000),
    "luwu timur": (-2.5333, 121.1167), "kepulauan selayar": (-6.1167, 120.4500),
    "maros": (-4.9833, 119.7000), "pangkajene kepulauan": (-4.7833, 119.5167),
    "barru": (-4.4000, 119.6000),
    # ── SULAWESI TENGGARA ──
    "kota kendari": (-3.9667, 122.5167), "kota bau-bau": (-5.4667, 122.6167),
    "konawe": (-3.8833, 122.4500), "konawe selatan": (-4.2333, 122.5167),
    "konawe utara": (-3.2833, 122.1667), "konawe kepulauan": (-3.9167, 123.1167),
    "kolaka": (-4.0500, 121.5833), "kolaka utara": (-3.3667, 121.3833),
    "kolaka timur": (-4.3500, 121.8333), "bombana": (-5.1167, 121.9667),
    "buton": (-5.4333, 122.7833), "buton tengah": (-5.0000, 122.4833),
    "buton utara": (-4.7667, 122.8167), "buton selatan": (-5.5000, 122.7000),
    "muna": (-4.9167, 122.6167), "muna barat": (-4.7833, 122.4167),
    "wakatobi": (-5.4833, 123.5500),
    # ── GORONTALO ──
    "kota gorontalo": (0.5500, 123.0667), "gorontalo": (0.5500, 122.5000),
    "gorontalo utara": (0.8833, 122.5000), "bone bolango": (0.5667, 123.2500),
    "pohuwato": (0.3833, 121.9667), "boalemo": (0.5000, 122.3833),
    # ── SULAWESI BARAT ──
    "kota mamuju": (-2.6667, 118.8833), "mamuju": (-2.6667, 118.9167),
    "mamuju utara": (-1.9500, 119.1500), "mamuju tengah": (-2.0333, 119.0500),
    "majene": (-3.5500, 118.9833), "polewali mandar": (-3.4333, 119.3333),
    "mamasa": (-2.9333, 119.3833),
    # ── MALUKU ──
    "kota ambon": (-3.6952, 128.1814), "kota tual": (-5.6333, 132.7500),
    "maluku tengah": (-3.3333, 128.5000), "seram bagian barat": (-3.0000, 128.1667),
    "seram bagian timur": (-3.2667, 130.0000), "maluku tenggara": (-5.6333, 132.7500),
    "maluku tenggara barat": (-7.9500, 131.3167), "kepulauan tanimbar": (-7.9833, 131.3333),
    "kepulauan aru": (-6.2000, 134.5333), "buru": (-3.3667, 126.7000),
    "buru selatan": (-3.7667, 126.5667),
    # ── MALUKU UTARA ──
    "kota ternate": (0.7833, 127.3833), "kota tidore kepulauan": (0.6667, 127.4167),
    "halmahera barat": (1.3333, 127.5167), "halmahera utara": (1.8333, 128.0833),
    "halmahera timur": (0.9167, 128.2833), "halmahera selatan": (-0.4167, 127.8833),
    "halmahera tengah": (0.5000, 128.1667), "kepulauan sula": (-1.8333, 125.4167),
    "pulau taliabu": (-1.8167, 124.6500), "pulau morotai": (2.3167, 128.2833),
    # ── PAPUA BARAT ──
    "kota sorong": (-0.8833, 131.2500), "sorong": (-0.8833, 131.2500),
    "sorong selatan": (-1.7500, 132.0000), "raja ampat": (-0.2333, 130.5167),
    "teluk bintuni": (-2.1167, 133.5167), "teluk wondama": (-2.7000, 134.2833),
    "manokwari": (-0.8667, 134.0833), "manokwari selatan": (-1.3833, 134.0833),
    "pegunungan arfak": (-1.3167, 133.6500), "kaimana": (-3.6500, 133.7500),
    "fakfak": (-2.9167, 132.2667), "maybrat": (-1.3333, 132.3167),
    "tambrauw": (-0.6333, 132.0000),
    # ── PAPUA ──
    "kota jayapura": (-2.5333, 140.7167), "jayapura": (-2.5667, 140.5000),
    "keerom": (-3.3000, 140.7500), "sarmi": (-1.8667, 138.7500),
    "mamberamo raya": (-1.7500, 137.7500), "mamberamo tengah": (-3.8333, 138.5000),
    "yalimo": (-3.9833, 138.9833), "lanny jaya": (-3.9500, 138.5000),
    "nduga": (-4.5000, 138.5000), "puncak": (-3.9167, 137.2667),
    "puncak jaya": (-3.5833, 137.1333), "intan jaya": (-3.8667, 136.5000),
    "dogiyai": (-3.9833, 136.1000), "deiyai": (-3.9500, 136.0667),
    "paniai": (-3.9833, 136.3000), "nabire": (-3.3667, 135.5000),
    "waropen": (-2.9833, 136.2333), "kepulauan yapen": (-1.8333, 136.2833),
    "biak numfor": (-1.1833, 136.0833), "supiori": (-0.7167, 135.5667),
    "merauke": (-8.4833, 140.4167), "mappi": (-6.5833, 139.3500),
    "asmat": (-5.5833, 138.5000), "boven digoel": (-6.0000, 140.0000),
    "pegunungan bintang": (-5.0000, 140.4167), "yahukimo": (-4.4833, 139.5167),
    "jayawijaya": (-3.9667, 138.9833), "tolikara": (-3.5333, 138.9833),
}

# ---------------------------------------------------------------------------
# Alias kota populer & singkatan yang sering muncul di berita
# ---------------------------------------------------------------------------
_ALIASES: dict[str, str] = {
    # Singkatan Jakarta
    "jakbar":  "jakarta barat",
    "jaktim":  "jakarta timur",
    "jaksel":  "jakarta selatan",
    "jakut":   "jakarta utara",
    "jakpus":  "jakarta pusat",
    "jakarta": "jakarta pusat",
    # Kota besar tanpa "kota"
    "bandung":   "kota bandung",
    "surabaya":  "kota surabaya",
    "medan":     "kota medan",
    "semarang":  "kota semarang",
    "makassar":  "kota makassar",
    "palembang": "kota palembang",
    "tangerang": "kota tangerang",
    "depok":     "kota depok",
    "bekasi":    "kota bekasi",
    "bogor":     "kota bogor",
    "pekanbaru": "kota pekanbaru",
    "batam":     "kota batam",
    "balikpapan":"kota balikpapan",
    "samarinda": "kota samarinda",
    "manado":    "kota manado",
    "ambon":     "kota ambon",
    "yogyakarta":"kota yogyakarta",
    "solo":      "kota surakarta",
    "surakarta": "kota surakarta",
    "malang":    "kota malang",
    "denpasar":  "kota denpasar",
    "mataram":   "kota mataram",
    "kupang":    "kota kupang",
    "jayapura":  "kota jayapura",
    "sorong":    "kota sorong",
    "ternate":   "kota ternate",
    "gorontalo": "kota gorontalo",
    "kendari":   "kota kendari",
    "palu":      "kota palu",
    "pontianak": "kota pontianak",
    "banjarmasin":"kota banjarmasin",
    "tarakan":   "kota tarakan",
    "bengkulu":  "kota bengkulu",
    "jambi":     "kota jambi",
    "padang":    "kota padang",
    "bandar lampung": "kota bandar lampung",
    "serang":    "kota serang",
    "cilegon":   "kota cilegon",
    "tegal":     "kota tegal",
    "pekalongan":"kota pekalongan",
    "magelang":  "kota magelang",
    "salatiga":  "kota salatiga",
    "kediri":    "kota kediri",
    "blitar":    "kota blitar",
    "mojokerto": "kota mojokerto",
    "madiun":    "kota madiun",
    "probolinggo":"kota probolinggo",
    "pasuruan":  "kota pasuruan",
    "batu":      "kota batu",
    # Kota-kota yang sering muncul di berita tanpa prefix "kota"
    "jatinangor":  "sumedang",
    "cibinong":    "kabupaten bogor",
    "cileungsi":   "kabupaten bogor",
    "cikarang":    "kabupaten bekasi",
    "karawang":    "kabupaten karawang",
    "purwakarta":  "kabupaten purwakarta",
    "subang":      "kabupaten subang",
    "cimahi":      "kota cimahi",
    "garut":       "kabupaten garut",
    "tasikmalaya": "kota tasikmalaya",
    "cianjur":     "kabupaten cianjur",
    "sukabumi":    "kota sukabumi",
    "cirebon":     "kota cirebon",
    "indramayu":   "kabupaten indramayu",
    "kuningan":    "kabupaten kuningan",
    "brebes":      "kabupaten brebes",
    "cilacap":     "kabupaten cilacap",
    "banyumas":    "kabupaten banyumas",
    "purbalingga": "kabupaten purbalingga",
    "kebumen":     "kabupaten kebumen",
    "klaten":      "kabupaten klaten",
    "boyolali":    "kabupaten boyolali",
    "wonogiri":    "kabupaten wonogiri",
    "grobogan":    "kabupaten grobogan",
    "kudus":       "kabupaten kudus",
    "jepara":      "kabupaten jepara",
    "pati":        "kabupaten pati",
    "rembang":     "kabupaten rembang",
    "blora":       "kabupaten blora",
    "sragen":      "kabupaten sragen",
    "karanganyar": "kabupaten karanganyar",
    "sukoharjo":   "kabupaten sukoharjo",
    "jombang":     "kabupaten jombang",
    "sidoarjo":    "kabupaten sidoarjo",
    "gresik":      "kabupaten gresik",
    "lamongan":    "kabupaten lamongan",
    "tuban":       "kabupaten tuban",
    "bojonegoro":  "kabupaten bojonegoro",
    "ngawi":       "kabupaten ngawi",
    "magetan":     "kabupaten magetan",
    "nganjuk":     "kabupaten nganjuk",
    "jember":      "kabupaten jember",
    "banyuwangi":  "kabupaten banyuwangi",
    "situbondo":   "kabupaten situbondo",
    "bondowoso":   "kabupaten bondowoso",
    "lumajang":    "kabupaten lumajang",
    "tulungagung": "kabupaten tulungagung",
    "trenggalek":  "kabupaten trenggalek",
    "ponorogo":    "kabupaten ponorogo",
    "pacitan":     "kabupaten pacitan",
    "sampang":     "kabupaten sampang",
    "pamekasan":   "kabupaten pamekasan",
    "sumenep":     "kabupaten sumenep",
    "bangkalan":   "kabupaten bangkalan",
    "singaraja":   "kabupaten buleleng",
    "gianyar":     "kabupaten gianyar",
    "tabanan":     "kabupaten tabanan",
    "badung":      "kabupaten badung",
    "buleleng":    "kabupaten buleleng",
    "bangli":      "kabupaten bangli",
    "klungkung":   "kabupaten klungkung",
    "karangasem":  "kabupaten karangasem",
    "lombok":      "kabupaten lombok tengah",
    "bima":        "kota bima",
    "dompu":       "kabupaten dompu",
    "sumbawa":     "kabupaten sumbawa",
    "pontianak":   "kota pontianak",
    "singkawang":  "kota singkawang",
    "sambas":      "kabupaten sambas",
    "ketapang":    "kabupaten ketapang",
    "sanggau":     "kabupaten sanggau",
    "palangkaraya":"kota palangka raya",
    "palangka raya":"kota palangka raya",
    "kotawaringin": "kabupaten kotawaringin barat",
    "banjarmasin": "kota banjarmasin",
    "banjarbaru":  "kota banjarbaru",
    "martapura":   "kabupaten banjar",
    "barabai":     "kabupaten hulu sungai tengah",
    "samarinda":   "kota samarinda",
    "balikpapan":  "kota balikpapan",
    "bontang":     "kota bontang",
    "kutai":       "kabupaten kutai kartanegara",
    "penajam":     "kabupaten penajam paser utara",
    "berau":       "kabupaten berau",
    "nunukan":     "kabupaten nunukan",
    "tanjung selor":"kota tanjung selor",
    "manado":      "kota manado",
    "bitung":      "kota bitung",
    "tomohon":     "kota tomohon",
    "kotamobagu":  "kota kotamobagu",
    "minahasa":    "kabupaten minahasa",
    "palu":        "kota palu",
    "donggala":    "kabupaten donggala",
    "sigi":        "kabupaten sigi",
    "poso":        "kabupaten poso",
    "luwuk":       "kabupaten banggai",
    "makassar":    "kota makassar",
    "pare-pare":   "kota pare-pare",
    "palopo":      "kota palopo",
    "gowa":        "kabupaten gowa",
    "maros":       "kabupaten maros",
    "bone":        "kabupaten bone",
    "wajo":        "kabupaten wajo",
    "soppeng":     "kabupaten soppeng",
    "sinjai":      "kabupaten sinjai",
    "bulukumba":   "kabupaten bulukumba",
    "bantaeng":    "kabupaten bantaeng",
    "jeneponto":   "kabupaten jeneponto",
    "takalar":     "kabupaten takalar",
    "pangkep":     "kabupaten pangkajene",
    "barru":       "kabupaten barru",
    "pinrang":     "kabupaten pinrang",
    "sidrap":      "kabupaten sidenreng rappang",
    "enrekang":    "kabupaten enrekang",
    "luwu":        "kabupaten luwu",
    "kendari":     "kota kendari",
    "bau-bau":     "kota bau-bau",
    "konawe":      "kabupaten konawe",
    "kolaka":      "kabupaten kolaka",
    "muna":        "kabupaten muna",
    "buton":       "kabupaten buton",
    "wakatobi":    "kabupaten wakatobi",
    "ambon":       "kota ambon",
    "masohi":      "kabupaten maluku tengah",
    "tual":        "kota tual",
    "ternate":     "kota ternate",
    "tidore":      "kota tidore kepulauan",
    "sofifi":      "kabupaten halmahera barat",
    "jayapura":    "kota jayapura",
    "sentani":     "kabupaten jayapura",
    "merauke":     "kabupaten merauke",
    "timika":      "kabupaten mimika",
    "biak":        "kabupaten biak numfor",
    "manokwari":   "kabupaten manokwari",
    "sorong":      "kota sorong",
    "fakfak":      "kabupaten fakfak",
    "nabire":      "kabupaten nabire",
    "wamena":      "kabupaten jayawijaya",
    "banda aceh":  "kota banda aceh",
    "lhokseumawe": "kota lhokseumawe",
    "langsa":      "kota langsa",
    "sabang":      "kota sabang",
    "subulussalam":"kota subulussalam",
    "medan":       "kota medan",
    "binjai":      "kota binjai",
    "tebing tinggi":"kota tebing tinggi",
    "padangsidimpuan":"kota padangsidimpuan",
    "gunungsitoli":"kota gunungsitoli",
    "lubuklinggau": "kota lubuklinggau",
    "prabumulih":  "kota prabumulih",
    "pagaralam":   "kota pagaralam",
    "bengkulu":    "kota bengkulu",
    "curup":       "kabupaten rejang lebong",
    "jambi":       "kota jambi",
    "sungai penuh":"kota sungai penuh",
    "tanjungpinang":"kota tanjungpinang",
    "batam":       "kota batam",
    "pekanbaru":   "kota pekanbaru",
    "dumai":       "kota dumai",
    "padang":      "kota padang",
    "bukittinggi": "kota bukittinggi",
    "payakumbuh":  "kota payakumbuh",
    "solok":       "kota solok",
    "sawahlunto":  "kota sawahlunto",
    "padangpanjang":"kota padangpanjang",
    "pariaman":    "kota pariaman",
    "bandar lampung":"kota bandar lampung",
    "metro":       "kota metro",
    "serang":      "kota serang",
    "cilegon":     "kota cilegon",
    "tangerang selatan":"kota tangerang selatan",
    "tangsel":     "kota tangerang selatan",
    "depok":       "kota depok",
    "bekasi":      "kota bekasi",
    "bogor":       "kota bogor",
    # Provinsi → ibukota sebagai fallback
    "lampung":        "kota bandar lampung",
    "banten":         "kota serang",
    "jawa barat":     "kota bandung",
    "jawa tengah":    "kota semarang",
    "jawa timur":     "kota surabaya",
    "sumatera utara": "kota medan",
    "sumatera selatan":"kota palembang",
    "sulawesi selatan":"kota makassar",
    "kalimantan timur":"kota samarinda",
    "kalimantan selatan":"kota banjarmasin",
    "papua":          "kota jayapura",
    "papua barat":    "kota sorong",
    "aceh":           "kota banda aceh",
    "riau":           "kota pekanbaru",
    "kepulauan riau": "kota tanjungpinang",
    "bali":           "kota denpasar",
    "ntb":            "kota mataram",
    "ntt":            "kota kupang",
    "maluku":         "kota ambon",
    "sulawesi utara": "kota manado",
    "sulawesi tengah":"kota palu",
    "gorontalo":      "kota gorontalo",
    "sulawesi barat": "kota mamuju",
    "maluku":         "kota ambon",
    "nusa tenggara barat": "kota mataram",
    "nusa tenggara timur": "kota kupang",
    "kalimantan barat": "kota pontianak",
    "kalimantan tengah": "kota palangka raya",
    "kalimantan utara": "kota tanjung selor",
    "sulawesi tenggara": "kota kendari",
    "di yogyakarta":  "kota yogyakarta",
    "dki jakarta":    "jakarta pusat",
    "kepulauan bangka belitung": "kota pangkalpinang",
    "sumatera barat": "kota padang",
    "bengkulu prov":  "kota bengkulu",
    "jambi prov":     "kota jambi",
}

# Kata kerja/kata umum bahasa Indonesia yang sering false-positive
_BLACKLIST: set[str] = {
    "buru", "muna", "luwu", "poso", "tebo", "ende", "pati",
    "blora", "rote", "alor", "biak", "bima", "palu", "tual",
    "demak", "gowa", "bone", "wajo", "bulukumba",
    # Nama institusi/frasa yang mengandung nama kota tapi bukan lokasi
    "metro jaya",   # Polda Metro Jaya → bukan Kota Metro Lampung
    "polda metro",
}

# Frasa yang harus diblokir bila muncul sebagai konteks nama kota
# Format: {nama_kota: [frasa_konteks_yang_invalid]}
_CONTEXT_BLACKLIST: dict[str, list[str]] = {
    "metro":    ["polda metro", "metro jaya", "kpk metro", "metro tv"],
    "palu":     ["berdampak palu", "palu hakim", "palu sidang"],
    "blitar":   ["kota blitar"],
    # "Berita Terkini Medan Sumut" = nama situs, bukan lokasi berita
    "medan":    ["berita terkini medan", "sumut terkini", "medan sumut"],
    "kota medan": ["berita terkini medan", "sumut terkini"],
}


def _load_cache() -> dict:
    if CACHE_PATH.exists():
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    return {}


def _save_cache(cache: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def _nominatim_lookup(nama: str) -> Optional[tuple[float, float]]:
    """Cari koordinat via Nominatim (OpenStreetMap). Rate-limit: 1 req/detik."""
    url    = "https://nominatim.openstreetmap.org/search"
    params = {"q": f"{nama}, Indonesia", "format": "json", "limit": 1}
    headers = {"User-Agent": "crime-health-map/1.0 (dimaslystianto11@gmail.com)"}
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
        results = resp.json()
        if results:
            return float(results[0]["lat"]), float(results[0]["lon"])
    except Exception:
        pass
    return None


def get_coords(nama_kabupaten: str) -> Optional[tuple[float, float]]:
    """
    Kembalikan (lat, lon) untuk nama kabupaten/kota.
    Urutan: alias → kamus statis → cache Nominatim → Nominatim API.
    """
    key = str(nama_kabupaten).strip().lower()

    # 0. Alias
    if key in _ALIASES:
        key = _ALIASES[key]

    # 1. Kamus statis (exact match)
    if key in _COORDS:
        return _COORDS[key]

    # 2. Partial match (hanya jika panjang key >= 5 agar tidak false-positive)
    if len(key) >= 5:
        for k, v in _COORDS.items():
            if key == k:
                return v
            # hanya match jika key adalah substring yang bermakna
            if len(key) >= 6 and (key in k and len(key) / len(k) > 0.5):
                return v

    # 3. Cache Nominatim
    cache = _load_cache()
    if key in cache:
        val = cache[key]
        return tuple(val) if val else None  # type: ignore

    # 4. Nominatim API (dengan rate-limit)
    time.sleep(1)
    coords = _nominatim_lookup(nama_kabupaten)
    cache[key] = list(coords) if coords else None
    _save_cache(cache)
    return coords


def batch_geocode(names: list[str], verbose: bool = True) -> dict[str, Optional[tuple[float, float]]]:
    """Geocode daftar nama kabupaten, kembalikan dict nama → (lat, lon)."""
    results: dict[str, Optional[tuple[float, float]]] = {}
    for i, nama in enumerate(names):
        coords = get_coords(nama)
        results[nama] = coords
        if verbose and (i + 1) % 20 == 0:
            print(f"[geocode] {i+1}/{len(names)} selesai ...")
    return results


if __name__ == "__main__":
    tests = ["karawang", "kota makassar", "jayapura", "manggarai barat", "xyz tidak ada"]
    for t in tests:
        c = get_coords(t)
        print(f"  {t:30s} -> {c}")
