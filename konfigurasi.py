"""Skema pengaturan laporan email, dipakai bersama oleh laporan.py dan dashboard.

Pengaturan disimpan di GitHub sebagai *Actions variable* bernama PENGATURAN (JSON).
Variable tidak terlihat oleh pengunjung repo publik, hanya oleh pemilik repo.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from fetchers import REGIONS, TIME_RANGES

VARIABLE_NAME = "PENGATURAN"
WORKFLOW_FILE = "laporan-harian.yml"

HARI = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]  # indeks = datetime.weekday()

EMAIL_RE = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")


def _tema_dari_file() -> list[str]:
    path = Path(__file__).parent / "tema.txt"
    if not path.exists():
        return []
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def default() -> dict:
    return {
        "aktif": True,
        "tema": _tema_dari_file() or ["harga beras"],
        "hari": list(range(7)),
        "jam": [7],
        "email_tujuan": [],
        "wilayah": "Indonesia (Bahasa Indonesia)",
        "rentang": "24 jam terakhir",
        "jumlah_isu": 5,
    }


def normalisasi(data: dict | None) -> dict:
    """Gabungkan dengan nilai default dan buang nilai yang tidak valid."""
    cfg = default()
    if not isinstance(data, dict):
        return cfg
    if isinstance(data.get("aktif"), bool):
        cfg["aktif"] = data["aktif"]
    if isinstance(data.get("tema"), list):
        cfg["tema"] = [str(t).strip() for t in data["tema"] if str(t).strip()][:20]
    if isinstance(data.get("hari"), list):
        cfg["hari"] = sorted({int(h) for h in data["hari"] if str(h).isdigit() and 0 <= int(h) <= 6})
    if isinstance(data.get("jam"), list):
        cfg["jam"] = sorted({int(j) for j in data["jam"] if str(j).isdigit() and 0 <= int(j) <= 23})
    if isinstance(data.get("email_tujuan"), list):
        cfg["email_tujuan"] = [e.strip() for e in data["email_tujuan"] if EMAIL_RE.match(str(e).strip())]
    if data.get("wilayah") in REGIONS:
        cfg["wilayah"] = data["wilayah"]
    if data.get("rentang") in TIME_RANGES:
        cfg["rentang"] = data["rentang"]
    try:
        cfg["jumlah_isu"] = max(1, min(10, int(data.get("jumlah_isu", cfg["jumlah_isu"]))))
    except (TypeError, ValueError):
        pass
    return cfg


def dari_json(text: str | None) -> dict:
    if not text:
        return default()
    try:
        return normalisasi(json.loads(text))
    except json.JSONDecodeError:
        return default()


def ke_json(cfg: dict) -> str:
    return json.dumps(normalisasi(cfg), ensure_ascii=False)
