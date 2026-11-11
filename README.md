# 📰 Pencari & Perangkum Isu Populer

Aplikasi web lokal: ketik sebuah tema → aplikasi mencari berita (Google News) dan diskusi (Reddit),
mengelompokkannya menjadi isu-isu, memberi peringkat popularitas, lalu merangkum tiap isu.
Tanpa AI dan tanpa API key — gratis.

## Cara menjalankan

1. Pasang Python 3.10+ (https://www.python.org/downloads/ — centang **Add Python to PATH**).
2. Buka terminal di folder ini, lalu:

```bash
pip install -r requirements.txt
```

```bash
streamlit run app.py
```

Browser akan terbuka di http://localhost:8501.

## Fitur
- Pilihan wilayah & bahasa (Indonesia, Malaysia, AS, Inggris, Singapura)
- Rentang waktu: 24 jam / 7 hari / 30 hari
- Sumber: Google News dan/atau Reddit
- Pengelompokan otomatis berita yang membahas hal yang sama (TF-IDF + kemiripan kosinus)
- Skor popularitas: jumlah artikel, keragaman sumber, upvote/komentar Reddit, kebaruan
- Ringkasan ekstraktif, sorotan, dan daftar sumber per isu
- Grafik kata kunci terpopuler
- Unduh hasil sebagai file Markdown

## Struktur
- `app.py` — antarmuka Streamlit
- `fetchers.py` — pengambil data Google News RSS & Reddit
- `summarizer.py` — pengelompokan, skor, dan perangkuman

## Catatan
- Reddit kadang memblokir akses tanpa login; aplikasi tetap jalan dengan Google News saja.
- Slider **Ketatnya pengelompokan** mengatur seberapa mirip berita harus agar digabung jadi satu isu.
