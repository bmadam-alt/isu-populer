"""Aplikasi web pencari & perangkum isu populer berdasarkan tema.

Jalankan:  streamlit run app.py
"""

from __future__ import annotations

from datetime import datetime

import streamlit as st

from fetchers import REGIONS, TIME_RANGES, fetch_google_news, fetch_reddit
from summarizer import build_issues, issues_to_markdown

st.set_page_config(page_title="Isu Populer", page_icon="📰", layout="wide")


@st.cache_data(ttl=900, show_spinner=False)
def cached_google(query, region, time_range):
    return fetch_google_news(query, region, time_range)


@st.cache_data(ttl=900, show_spinner=False)
def cached_reddit(query, time_range):
    return fetch_reddit(query, time_range)


# ---------- Sidebar: pengaturan ----------
with st.sidebar:
    st.header("⚙️ Pengaturan")
    region = st.selectbox("Wilayah & bahasa berita", list(REGIONS.keys()), index=0)
    time_range = st.selectbox("Rentang waktu", list(TIME_RANGES.keys()), index=1)
    st.markdown("**Sumber**")
    use_google = st.checkbox("Google News", value=True)
    use_reddit = st.checkbox("Reddit", value=True)
    max_issues = st.slider("Jumlah isu ditampilkan", 3, 20, 8)
    threshold = st.slider(
        "Ketatnya pengelompokan",
        0.10,
        0.60,
        0.25,
        0.05,
        help="Makin tinggi, makin spesifik tiap isu (lebih banyak isu kecil). "
        "Makin rendah, berita yang agak mirip digabung jadi satu isu.",
    )
    st.caption("Data di-cache 15 menit agar tidak membebani sumber.")

# ---------- Halaman utama ----------
st.title("📰 Pencari & Perangkum Isu Populer")
st.write("Ketik tema, lalu aplikasi akan mencari berita & diskusi terkini, "
         "mengelompokkannya menjadi isu, dan merangkum masing-masing isu.")

with st.form("cari"):
    col1, col2 = st.columns([5, 1])
    query = col1.text_input("Tema", placeholder="contoh: kendaraan listrik, pemilu, harga beras, AI",
                            label_visibility="collapsed")
    submitted = col2.form_submit_button("🔍 Cari", width="stretch")

if submitted:
    query = query.strip()
    if not query:
        st.warning("Masukkan tema terlebih dahulu.")
        st.stop()
    if not (use_google or use_reddit):
        st.warning("Pilih minimal satu sumber di sidebar.")
        st.stop()

    items, errors = [], []
    with st.spinner("Mengambil berita dan diskusi..."):
        if use_google:
            try:
                items += cached_google(query, region, time_range)
            except Exception as e:  # noqa: BLE001
                errors.append(f"Google News gagal diambil: {e}")
        if use_reddit:
            try:
                items += cached_reddit(query, time_range)
            except Exception as e:  # noqa: BLE001
                errors.append(f"Reddit gagal diambil: {e} (Reddit kadang membatasi akses tanpa login)")

    for err in errors:
        st.warning(err)

    if not items:
        st.error("Tidak ada hasil. Coba tema lain atau perpanjang rentang waktu.")
        st.stop()

    with st.spinner("Mengelompokkan dan merangkum isu..."):
        issues, keywords = build_issues(items, query, threshold=threshold, max_issues=max_issues)

    st.session_state["hasil"] = {
        "query": query,
        "issues": issues,
        "keywords": keywords,
        "n_items": len(items),
        "n_sources": len({it.source for it in items}),
        "meta": f"{region} · {time_range} · dibuat {datetime.now():%d %b %Y %H:%M}",
    }

hasil = st.session_state.get("hasil")
if hasil:
    issues = hasil["issues"]
    st.subheader(f"Hasil untuk “{hasil['query']}”")
    st.caption(hasil["meta"])

    m1, m2, m3 = st.columns(3)
    m1.metric("Artikel & diskusi", hasil["n_items"])
    m2.metric("Sumber berbeda", hasil["n_sources"])
    m3.metric("Isu ditemukan", len(issues))

    left, right = st.columns([3, 1])

    with right:
        st.markdown("#### 🔑 Kata kunci terpopuler")
        top_kw = hasil["keywords"].most_common(12)
        if top_kw:
            st.bar_chart(
                [{"Kata": k, "Jumlah": v} for k, v in top_kw],
                x="Kata", y="Jumlah", horizontal=True, sort="-Jumlah", height=380,
            )
        st.download_button(
            "⬇️ Unduh ringkasan (Markdown)",
            issues_to_markdown(issues, hasil["query"], hasil["meta"]),
            file_name=f"isu-{hasil['query'].replace(' ', '-')}.md",
            mime="text/markdown",
            width="stretch",
        )

    with left:
        for rank, iss in enumerate(issues, 1):
            with st.container(border=True):
                pf = iss.platforms
                badges = " ".join(
                    [f"`{k}: {v}`" for k, v in pf.items()] + [f"`skor {iss.score}`"]
                )
                st.markdown(f"### {rank}. {iss.label}")
                st.markdown(badges)
                st.write(iss.summary)
                if iss.highlights:
                    st.markdown("**Sorotan lain:**\n" + "\n".join(f"- {h}" for h in iss.highlights))
                with st.expander(f"Lihat {len(iss.items)} sumber"):
                    for it in iss.items:
                        tgl = it.published.astimezone().strftime("%d %b %Y %H:%M") if it.published else ""
                        extra = f" · ⬆️ {it.score:,} · 💬 {it.comments:,}" if (it.score or it.comments) else ""
                        st.markdown(f"- [{it.title}]({it.link})  \n  _{it.source} · {tgl}{extra}_")
else:
    st.info("Masukkan tema di atas untuk mulai. Atur wilayah, waktu, dan sumber di sidebar kiri.")
