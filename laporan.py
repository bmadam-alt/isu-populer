"""Laporan isu populer otomatis yang dikirim lewat email.

Dijalankan terjadwal oleh GitHub Actions (lihat .github/workflows/laporan-harian.yml),
tapi bisa juga dijalankan manual:

    python laporan.py --preview      # simpan laporan.html tanpa mengirim email
    python laporan.py                # kirim email (butuh variabel lingkungan di bawah)

Variabel lingkungan:
    GMAIL_USER          alamat Gmail pengirim
    GMAIL_APP_PASSWORD  App Password Gmail (16 huruf, bukan kata sandi utama)
    EMAIL_TO            penerima, boleh beberapa dipisah koma (default: GMAIL_USER)
    WILAYAH             default "Indonesia (Bahasa Indonesia)"
    RENTANG             default "24 jam terakhir"
    JUMLAH_ISU          default 5 isu per tema
    SEGARKAN_JAM        default 6: di luar jam kirim, data isu untuk Studio Konten
                        diperbarui (tanpa email) bila sudah setua ini
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import smtplib
import sys
import time
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from fetchers import REGIONS, TIME_RANGES, fetch_google_news, fetch_reddit
from konfigurasi import HARI, dari_json
from summarizer import build_issues, issues_to_markdown

HERE = Path(__file__).parent
WIB = timezone(timedelta(hours=7))
BERKAS_DATA = HERE / "data" / "isu-terbaru.json"
SEGARKAN_JAM = float(os.environ.get("SEGARKAN_JAM") or 6)


def umur_data(now: datetime) -> float | None:
    """Umur data/isu-terbaru.json dalam jam, atau None bila belum ada atau tidak terbaca."""
    try:
        dibuat = datetime.fromisoformat(json.loads(BERKAS_DATA.read_text(encoding="utf-8"))["dibuat"])
        return (now - dibuat).total_seconds() / 3600
    except Exception:  # noqa: BLE001
        return None


def tandai_data_baru() -> None:
    """Beri tahu workflow bahwa ada data baru, supaya langkah perkaya dan simpan dijalankan."""
    keluaran = os.environ.get("GITHUB_OUTPUT")
    if keluaran:
        with open(keluaran, "a", encoding="utf-8") as f:
            f.write("baru=true\n")


def collect(theme: str, region: str, rentang: str, jumlah: int):
    items, notes = [], []
    try:
        items += fetch_google_news(theme, region, rentang)
    except Exception as e:  # noqa: BLE001
        notes.append(f"Google News gagal: {e}")
    try:
        items += fetch_reddit(theme, rentang)
    except Exception:  # noqa: BLE001 - Reddit sering memblokir server; abaikan
        pass
    issues, _ = build_issues(items, theme, max_issues=jumlah) if items else ([], None)
    return issues, len(items), notes


def fmt(dt) -> str:
    return dt.astimezone(WIB).strftime("%d %b %H:%M") if dt else ""


def render_html(sections, title: str, meta: str) -> str:
    e = html.escape
    out = [
        "<div style='font-family:Arial,sans-serif;max-width:720px;margin:auto;color:#222'>",
        f"<h1 style='font-size:22px;margin-bottom:4px'>{e(title)}</h1>",
        f"<p style='color:#777;font-size:13px;margin-top:0'>{e(meta)}</p>",
    ]
    for theme, issues, n_items, notes in sections:
        out.append(
            f"<h2 style='font-size:19px;border-bottom:2px solid #e33;padding-bottom:4px;margin-top:28px'>"
            f"Tema: {e(theme)} <span style='font-size:13px;color:#777;font-weight:normal'>"
            f"({n_items} artikel)</span></h2>"
        )
        for n in notes:
            out.append(f"<p style='color:#b60'>⚠️ {e(n)}</p>")
        if not issues:
            out.append("<p style='color:#777'>Tidak ada isu baru pada periode ini.</p>")
        for rank, iss in enumerate(issues, 1):
            out.append(
                "<div style='border:1px solid #ddd;border-radius:8px;padding:12px 16px;margin:12px 0'>"
                f"<h3 style='font-size:16px;margin:0 0 6px'>{rank}. {e(iss.label)} "
                f"<span style='font-size:12px;color:#999;font-weight:normal'>skor {iss.score}</span></h3>"
                f"<p style='margin:6px 0;line-height:1.5'>{e(iss.summary)}</p>"
            )
            if iss.highlights:
                out.append("<ul style='margin:6px 0;padding-left:20px;color:#444'>")
                out += [f"<li>{e(h)}</li>" for h in iss.highlights]
                out.append("</ul>")
            out.append("<p style='margin:8px 0 0;font-size:13px'><b>Baca:</b></p><ul style='margin:2px 0;padding-left:20px;font-size:13px'>")
            for it in iss.items[:5]:
                out.append(
                    f"<li><a href='{e(it.link)}'>{e(it.title)}</a> "
                    f"<span style='color:#888'>— {e(it.source)}, {fmt(it.published)}</span></li>"
                )
            out.append("</ul></div>")
    out.append(
        "<p style='color:#999;font-size:12px;margin-top:30px'>Dikirim otomatis oleh aplikasi Isu Populer. "
        "Ubah tema, jadwal, dan penerima di halaman Pengaturan aplikasi. "
        "Isu di email ini juga bisa dipilih langsung di Studio Konten (menu Isu) untuk dibuat menjadi konten.</p></div>"
    )
    return "\n".join(out)


def _iso(dt) -> str | None:
    return dt.astimezone(WIB).isoformat(timespec="minutes") if dt else None


def simpan_json(sections, now: datetime, meta: str) -> bool:
    """Simpan laporan sebagai data/isu-terbaru.json untuk dibaca aplikasi Studio Konten.

    Berkas ini ikut di-commit oleh GitHub Actions, sehingga isu yang sama dengan isi email
    bisa dipilih langsung di Studio Konten tanpa menyalin dari email.
    Bila pengumpulan tidak menghasilkan satu isu pun (misalnya Google sedang menolak),
    data lama tidak ditimpa supaya daftar isu di Studio Konten tidak kosong.
    """
    isu = []
    for theme, issues, n_items, notes in sections:
        for rank, iss in enumerate(issues, 1):
            kunci = f"{now:%Y%m%d}|{theme}|{iss.headline.link if iss.headline else iss.label}"
            isu.append({
                "id": hashlib.sha1(kunci.encode("utf-8")).hexdigest()[:12],
                "tema": theme,
                "peringkat": rank,
                "label": iss.label,
                "skor": iss.score,
                "ringkasan": iss.summary,
                "judul_utama": iss.headline.title if iss.headline else "",
                "kata_kunci": iss.keywords,
                "sorotan": iss.highlights,
                "sumber": [
                    {
                        "judul": it.title,
                        "tautan": it.link,
                        "media": it.source,
                        "platform": it.platform,
                        "terbit": _iso(it.published),
                        "cuplikan": (it.snippet or "")[:400],
                    }
                    for it in iss.items[:8]
                ],
            })
    if not isu and BERKAS_DATA.exists():
        print("Tidak ada isu terkumpul; data isu lama dipertahankan.")
        return False
    data = {
        "dibuat": now.isoformat(timespec="minutes"),
        "keterangan": meta,
        "tema": [s[0] for s in sections],
        "isu": isu,
    }
    out = BERKAS_DATA
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Data isu disimpan di {out.relative_to(HERE)} ({len(isu)} isu)")
    tandai_data_baru()
    return True


def send_email(subject: str, html_body: str, text_body: str, recipients: list[str]) -> None:
    user = os.environ.get("GMAIL_USER", "").strip()
    password = os.environ.get("GMAIL_APP_PASSWORD", "").replace(" ", "").strip()
    if not user or not password:
        sys.exit("GMAIL_USER dan GMAIL_APP_PASSWORD belum diatur (lihat PANDUAN-EMAIL.md).")
    if not recipients:
        to = os.environ.get("EMAIL_TO", "").strip() or user
        recipients = [a.strip() for a in to.split(",") if a.strip()]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"Isu Populer <{user}>"
    # Penerima dikirim sebagai BCC agar tidak saling melihat alamat satu sama lain
    msg["To"] = recipients[0] if len(recipients) == 1 else f"Isu Populer <{user}>"
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    # Pemeriksaan ringan tanpa menampilkan isi rahasia
    print(f"GMAIL_USER: {'ok' if '@' in user else 'TIDAK VALID (harus alamat email lengkap)'}")
    print(f"GMAIL_APP_PASSWORD: {len(password)} karakter "
          f"({'ok' if len(password) == 16 and password.isalpha() else 'seharusnya 16 huruf tanpa spasi'})")

    def send_once():
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
            smtp.ehlo()
            # Pakai AUTH PLAIN saja. Jika login ditolak, smtplib biasanya mencoba AUTH LOGIN,
            # lalu Gmail memutus koneksi sehingga pesan error aslinya hilang.
            smtp.esmtp_features["auth"] = "PLAIN"
            smtp.login(user, password)
            smtp.sendmail(user, recipients, msg.as_string())

    last_err = None
    for attempt in range(1, 4):
        try:
            send_once()
            # Log repo publik bisa dilihat orang lain: jangan tampilkan alamat email
            print(f"Email terkirim ke {len(recipients)} penerima")
            return
        except smtplib.SMTPAuthenticationError as e:
            sys.exit(
                f"Gmail menolak login (kode {e.smtp_code}: Username and Password not accepted).\n"
                "Periksa secret GMAIL_USER (alamat Gmail lengkap) dan GMAIL_APP_PASSWORD "
                "(App Password 16 huruf dari akun Gmail yang SAMA, belum dihapus)."
            )
        except (smtplib.SMTPException, OSError) as e:
            last_err = e
            print(f"Percobaan {attempt} gagal: {type(e).__name__}: {e}")
            time.sleep(10 * attempt)
    sys.exit(f"Gagal mengirim email setelah 3 percobaan: {last_err}")


def waktunya_kirim(cfg: dict, now: datetime) -> tuple[bool, str]:
    """Untuk jalan terjadwal (tiap jam): kirim hanya pada hari & jam yang dipilih."""
    if not cfg["aktif"]:
        return False, "Laporan otomatis sedang dinonaktifkan di dashboard."
    if now.weekday() not in cfg["hari"]:
        return False, f"Hari ini ({HARI[now.weekday()]}) tidak termasuk hari kirim."
    if now.hour not in cfg["jam"]:
        jam = ", ".join(f"{j:02d}:00" for j in cfg["jam"]) or "-"
        return False, f"Sekarang {now:%H:%M} WIB; jam kirim: {jam}."
    return True, ""


def main() -> None:
    preview = "--preview" in sys.argv
    now = datetime.now(WIB)

    # Pengaturan dari dashboard (GitHub Actions variable PENGATURAN), atau default + tema.txt
    cfg = dari_json(os.environ.get("PENGATURAN"))
    for key, env in (("wilayah", "WILAYAH"), ("rentang", "RENTANG")):
        if os.environ.get(env):
            cfg[key] = os.environ[env]
    if os.environ.get("JUMLAH_ISU"):
        cfg["jumlah_isu"] = int(os.environ["JUMLAH_ISU"])
    region, rentang, jumlah = cfg["wilayah"], cfg["rentang"], cfg["jumlah_isu"]
    if region not in REGIONS:
        sys.exit(f"WILAYAH tidak dikenal: {region}. Pilihan: {', '.join(REGIONS)}")
    if rentang not in TIME_RANGES:
        sys.exit(f"RENTANG tidak dikenal: {rentang}. Pilihan: {', '.join(TIME_RANGES)}")

    kirim = True
    if os.environ.get("GITHUB_EVENT_NAME") == "schedule" and not preview:
        ok, alasan = waktunya_kirim(cfg, now)
        if not ok:
            # Di luar jam kirim: email tidak dikirim, tetapi data isu untuk Studio Konten
            # diperbarui bila sudah berumur SEGARKAN_JAM (toleransi 30 menit untuk jadwal GitHub
            # yang sering terlambat). Jadwal ini mengikuti jam kirim email, misalnya 21, 03, 09, 15.
            umur = umur_data(now)
            if umur is not None and umur < SEGARKAN_JAM - 0.5:
                print(f"Tidak mengirim: {alasan} Data isu masih segar ({umur:.1f} jam).")
                return
            print(f"Tidak mengirim email: {alasan} Data isu diperbarui"
                  + (f" (umur sebelumnya {umur:.1f} jam)." if umur is not None else "."))
            kirim = False

    themes = cfg["tema"]
    if not themes:
        sys.exit("Belum ada tema. Tambahkan tema di dashboard Pengaturan atau di tema.txt.")
    sections, md_parts = [], []
    for theme in themes:
        print(f"Memproses tema: {theme}")
        issues, n_items, notes = collect(theme, region, rentang, jumlah)
        sections.append((theme, issues, n_items, notes))
        md_parts.append(issues_to_markdown(issues, theme, f"{region} · {rentang}"))

    title = f"Isu Populer {now:%d %b %Y}"
    meta = f"{region} · {rentang} · {now:%d %b %Y %H:%M} WIB · {len(themes)} tema"
    html_body = render_html(sections, title, meta)
    text_body = "\n\n".join(md_parts)
    simpan_json(sections, now, meta)

    if not kirim:
        return
    if preview:
        out = HERE / "laporan.html"
        out.write_text(html_body, encoding="utf-8")
        print(f"Pratinjau disimpan di {out}")
        return
    send_email(f"📰 {title}: " + ", ".join(themes)[:80], html_body, text_body, cfg["email_tujuan"])


if __name__ == "__main__":
    main()
