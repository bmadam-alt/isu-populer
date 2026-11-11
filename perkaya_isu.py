"""Memperkaya data/isu-terbaru.json dengan isi artikel, untuk bahan tulisan Studio Konten.

Untuk setiap isu teratas:
1. Tautan Google News di daftar sumber diurai menjadi alamat artikel asli, lalu beberapa
   paragraf awal artikel dibaca (bukan disalin ke konten; hanya bahan rujukan AI).
2. Artikel terkait dari media lain dicari lewat pencarian Google News (7 hari terakhir),
   supaya bahasan bisa lebih lengkap.
Hasilnya disimpan di field "artikel" pada tiap isu: [{media, judul, url, jenis, teks_terkunci}].

Teks artikel adalah karya berhak cipta media aslinya. Karena repo ini publik, teks itu TIDAK disimpan
terbuka: teks dienkripsi dengan rahasia ISU_KUNCI (GitHub Secrets) dan hanya dibuka oleh fungsi
server Studio Konten yang memegang rahasia yang sama. Tanpa ISU_KUNCI, teks tidak disimpan sama sekali
(hanya media, judul, dan alamat artikel).

Hanya memakai pustaka bawaan Python. Kegagalan per artikel diabaikan; email laporan tidak
terpengaruh karena skrip ini berjalan setelah laporan.py.

    python perkaya_isu.py            # memperkaya data/isu-terbaru.json
    python perkaya_isu.py --uji 2    # coba 2 isu teratas, cetak ringkasan, tidak menulis berkas
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import os
import secrets
import re
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
BERKAS = HERE / "data" / "isu-terbaru.json"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
TIMEOUT = 12
MAKS_ISU = 12          # isu teratas yang diperkaya
MAKS_UTAMA = 3         # artikel dari daftar sumber isu
MAKS_TERKAIT = 2       # artikel terkait dari media lain
MAKS_TEKS = 1800       # karakter per artikel
MAKS_TOTAL = 8000      # karakter artikel per isu

TOLAK_BARIS = re.compile(
    r"baca juga|baca selengkapnya|advertisement|scroll to continue|copyright|hak cipta|"
    r"ikuti kami|follow us|download aplikasi|simak berita|klik di sini|whatsapp channel|"
    r"google news|editor:|penulis:|reporter:|sumber foto|^foto:", re.I)


def ambil(url: str, data: bytes | None = None, headers: dict | None = None) -> tuple[str, str]:
    """Mengembalikan (url akhir, teks halaman)."""
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, "Accept-Language": "id,en;q=0.8", **(headers or {})})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        mentah = r.read(3_000_000)
        cs = r.headers.get_content_charset() or "utf-8"
        return r.geturl(), mentah.decode(cs, errors="replace")


# --- 0. Enkripsi teks artikel (SHA-256 mode pencacah + HMAC, pustaka bawaan) ----------------

def _kunci() -> tuple[bytes, bytes] | None:
    rahasia = os.environ.get("ISU_KUNCI", "").strip()
    if not rahasia:
        return None
    k = hashlib.sha256(rahasia.encode("utf-8")).digest()
    return hashlib.sha256(k + b"enc").digest(), hashlib.sha256(k + b"mac").digest()


def kunci_teks(teks: str, kunci: tuple[bytes, bytes]) -> str:
    data = teks.encode("utf-8")
    nonce = secrets.token_bytes(16)
    aliran = b"".join(hashlib.sha256(kunci[0] + nonce + i.to_bytes(8, "big")).digest() for i in range((len(data) + 31) // 32))
    sandi = bytes(a ^ b for a, b in zip(data, aliran))
    tag = hmac.new(kunci[1], nonce + sandi, hashlib.sha256).digest()
    return base64.b64encode(nonce + tag + sandi).decode("ascii")


# --- 1. Mengurai tautan Google News -------------------------------------------------------

def urai_google_news(url: str) -> str | None:
    m = re.search(r"news\.google\.com/(?:rss/)?articles/([^?/#]+)", url)
    if not m:
        return url
    gid = m.group(1)
    try:
        _, hal = ambil(f"https://news.google.com/rss/articles/{gid}")
        sg = re.search(r'data-n-a-sg="([^"]+)"', hal)
        ts = re.search(r'data-n-a-ts="([^"]+)"', hal)
        if not (sg and ts):
            return None
        inti = ('["garturlreq",[["X","X",["X","X"],null,null,1,1,"US:en",null,1,null,null,null,null,null,0,1],'
                f'"X","X",1,[1,1,1],1,1,null,0,0,null,0],"{gid}",{ts.group(1)},"{sg.group(1)}"]')
        badan = "f.req=" + urllib.parse.quote(json.dumps([[["Fbv4je", inti, None, "generic"]]]))
        _, jaw = ambil("https://news.google.com/_/DotsSplashUi/data/batchexecute", badan.encode(),
                       {"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"})
        bagian = jaw.split("\n\n", 1)[1]
        data = json.loads(bagian)
        for baris in data:
            if isinstance(baris, list) and len(baris) > 2 and baris[1] == "Fbv4je" and baris[2]:
                hasil = json.loads(baris[2])
                if isinstance(hasil, list) and len(hasil) > 1 and str(hasil[1]).startswith("http"):
                    return hasil[1]
    except Exception:
        return None
    return None


# --- 2. Membaca isi artikel ----------------------------------------------------------------

def teks_artikel(hal: str) -> str:
    hal = re.sub(r"(?is)<(script|style|noscript|svg|iframe|form|nav|footer|aside|header|figure)[^>]*>.*?</\1>", " ", hal)
    m = re.search(r"(?is)<article[^>]*>(.*?)</article>", hal)
    inti = m.group(1) if m and len(m.group(1)) > 1500 else hal
    paragraf = []
    for p in re.findall(r"(?is)<p[^>]*>(.*?)</p>", inti):
        t = html.unescape(re.sub(r"(?s)<[^>]+>", " ", p))
        t = re.sub(r"\s+", " ", t).strip()
        if len(t) < 60 or TOLAK_BARIS.search(t):
            continue
        if paragraf and t == paragraf[-1]:
            continue
        paragraf.append(t)
    teks = ""
    for t in paragraf:
        if len(teks) + len(t) > MAKS_TEKS:
            break
        teks += t + "\n"
    return teks.strip()


def baca(url: str) -> tuple[str, str] | None:
    """(url akhir, teks) atau None bila gagal/terlalu pendek (mis. berbayar)."""
    try:
        akhir, hal = ambil(url)
        t = teks_artikel(hal)
        return (akhir, t) if len(t) >= 300 else None
    except Exception:
        return None


# --- 3. Artikel terkait lewat pencarian Google News ----------------------------------------

def kata_kunci(isu: dict) -> list[str]:
    kata = [k.strip() for k in str(isu.get("label", "")).split("·") if len(k.strip()) > 2]
    return kata[:4]


def cari_terkait(isu: dict, media_dipakai: set[str]) -> list[dict]:
    """Berita lain tentang isu yang sama dari media yang belum dipakai (7 hari terakhir)."""
    kata = kata_kunci(isu)
    for n in (len(kata), 2):
        if n < 2:
            continue
        q = " ".join(kata[:n]) + " when:7d"
        url = "https://news.google.com/rss/search?" + urllib.parse.urlencode({"q": q, "hl": "id", "gl": "ID", "ceid": "ID:id"})
        try:
            _, xml = ambil(url)
        except Exception:
            continue
        hasil = []
        for item in re.findall(r"(?s)<item>(.*?)</item>", xml):
            link = re.search(r"<link>(.*?)</link>", item)
            sumber = re.search(r"<source[^>]*>(.*?)</source>", item)
            judul = re.search(r"<title>(.*?)</title>", item)
            media = html.unescape(sumber.group(1)).strip() if sumber else ""
            if not link or not media or media.lower() in media_dipakai:
                continue
            media_dipakai.add(media.lower())
            hasil.append({"tautan": html.unescape(link.group(1)), "media": media,
                          "judul": html.unescape(judul.group(1)).rsplit(" - ", 1)[0] if judul else ""})
            if len(hasil) >= MAKS_TERKAIT * 3:
                break
        if hasil:
            return hasil
    return []


def domain(url: str) -> str:
    return re.sub(r"^www\.", "", urllib.parse.urlparse(url).netloc.lower())


def perkaya(isu: dict) -> list[dict]:
    artikel: list[dict] = []
    domain_dipakai: set[str] = set()

    sumber = isu.get("sumber") or []
    with ThreadPoolExecutor(4) as ex:
        alamat = list(ex.map(lambda s: urai_google_news(s.get("tautan", "")), sumber[:6]))
    calon = [(s, u) for s, u in zip(sumber[:6], alamat) if u]
    with ThreadPoolExecutor(4) as ex:
        dibaca = list(ex.map(lambda su: baca(su[1]), calon))
    for (s, _), b in zip(calon, dibaca):
        if not b or len([a for a in artikel if a["jenis"] == "sumber"]) >= MAKS_UTAMA:
            continue
        d = domain(b[0])
        if d in domain_dipakai:
            continue
        domain_dipakai.add(d)
        artikel.append({"jenis": "sumber", "media": s.get("media") or d, "judul": s.get("judul", ""), "url": b[0], "teks": b[1]})

    media_dipakai = {str(s.get("media", "")).lower() for s in sumber}
    for t in cari_terkait(isu, media_dipakai):
        if len([a for a in artikel if a["jenis"] == "terkait"]) >= MAKS_TERKAIT:
            break
        u = urai_google_news(t["tautan"])
        b = baca(u) if u else None
        if b and domain(b[0]) not in domain_dipakai:
            domain_dipakai.add(domain(b[0]))
            artikel.append({"jenis": "terkait", "media": t["media"], "judul": t["judul"], "url": b[0], "teks": b[1]})

    total, hasil = 0, []
    for a in artikel:
        if total + len(a["teks"]) > MAKS_TOTAL:
            break
        total += len(a["teks"])
        hasil.append(a)
    return hasil


def main() -> int:
    uji = "--uji" in sys.argv
    n_uji = int(sys.argv[sys.argv.index("--uji") + 1]) if uji and len(sys.argv) > sys.argv.index("--uji") + 1 else 2
    if not BERKAS.exists():
        print(f"{BERKAS} belum ada; tidak ada yang diperkaya.")
        return 0
    data = json.loads(BERKAS.read_text(encoding="utf-8"))
    daftar = sorted(data.get("isu", []), key=lambda i: -(i.get("skor") or 0))[: (n_uji if uji else MAKS_ISU)]
    t0 = time.time()

    def kerjakan(isu: dict) -> None:
        try:
            isu["artikel"] = perkaya(isu)
        except Exception as e:  # satu isu gagal tidak menghentikan yang lain
            isu["artikel"] = []
            print(f"  gagal: {isu.get('label')}: {e}")

    with ThreadPoolExecutor(3) as ex:
        list(ex.map(kerjakan, daftar))
    for isu in daftar:
        print(f"- {isu.get('label')}: {len(isu['artikel'])} artikel "
              f"({', '.join(a['media'] + ('*' if a['jenis'] == 'terkait' else '') for a in isu['artikel'])})", flush=True)
    print(f"Selesai dalam {time.time() - t0:.0f} detik (* = artikel terkait dari media lain).")
    if uji:
        if daftar and daftar[0].get("artikel"):
            a = daftar[0]["artikel"][0]
            print(f"\nContoh [{a['media']}] {a['url']}\n{a['teks'][:600]}…")
        return 0
    kunci = _kunci()
    for isu in data.get("isu", []):
        for a in isu.get("artikel") or []:
            teks = a.pop("teks", "")
            if kunci and teks:
                a["teks_terkunci"] = kunci_teks(teks, kunci)
    if not kunci:
        print("ISU_KUNCI belum diatur: teks artikel tidak disimpan (hanya media, judul, dan alamat).")
    BERKAS.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
