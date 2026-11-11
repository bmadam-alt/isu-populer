"""Pengelompokan dan perangkuman isu tanpa AI.

Cara kerja:
1. Setiap judul/cuplikan diubah menjadi vektor kata berbobot TF-IDF.
2. Artikel yang mirip (kemiripan kosinus >= ambang) digabung menjadi satu isu.
3. Isu diberi skor popularitas: jumlah artikel, keragaman sumber,
   interaksi Reddit, dan kebaruan.
4. Ringkasan dibuat secara ekstraktif: judul paling representatif,
   kata kunci utama, serta kalimat pendukung dari artikel lain.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone

from fetchers import Item

STOPWORDS_ID = set("""
ada adalah agar akan aku anda antara apa apakah atas atau bagai bagaimana bagi bahkan bahwa baik banyak baru
beberapa begitu belum benar berapa berbagai bersama besar bisa boleh buat bukan cara dalam dan dapat dari
demikian dengan di dia diri dua hal hanya harus hari hingga ia ialah ini itu jadi jangan jika juga justru kalau
kami kamu kan kapan karena kata ke kecil kembali kemudian kenapa kepada ketika kini kita lagi lain lalu lama
lebih maka mampu mana masih masing melalui memang mereka meski mulai namun oleh pada para pasti per perlu
pula pun sama sampai sangat satu saat saja salah sebagai sebelum secara sedang segera sehingga sejak sekali
sekitar selain selama seluruh semua sementara sendiri seperti serta sesuai setelah setiap siapa soal sudah
supaya tahun tak tanpa tapi telah tentang terhadap terjadi termasuk tersebut tetap tetapi tiga tidak tiap
untuk usai waktu yaitu yakni yang begini nya lah pun kah dll dsb jl tsb ya oh wah hingga bakal disebut
mengatakan menurut ungkap kata simak berikut terbaru hari ini kemarin besok update video foto viral
empat lima enam tujuh delapan sembilan sepuluh puluh ratus ribu juta siap kini resmi jadi bikin
""".split())

STOPWORDS_EN = set("""
a about above after again against all am an and any are as at be because been before being below between
both but by can could did do does doing down during each few for from further had has have having he her here
hers herself him himself his how i if in into is it its itself just me more most my myself no nor not now of
off on once only or other our ours out over own same she should so some such than that the their theirs them
then there these they this those through to too under until up very was we were what when where which while
who whom why will with would you your yours new says said say after amid over via vs how why what latest news
update live watch video photos today yesterday week report reports
""".split())

STOPWORDS = STOPWORDS_ID | STOPWORDS_EN

TOKEN_RE = re.compile(r"[a-zA-ZÀ-ɏ0-9]+")


def tokenize(text: str) -> list[str]:
    tokens = []
    for tok in TOKEN_RE.findall(text.lower()):
        if len(tok) < 3 or tok in STOPWORDS or tok.isdigit():
            continue
        tokens.append(tok)
    return tokens


@dataclass
class Issue:
    items: list[Item]
    keywords: list[str] = field(default_factory=list)
    label: str = ""
    headline: Item | None = None
    summary: str = ""
    highlights: list[str] = field(default_factory=list)
    score: float = 0.0

    @property
    def sources(self) -> set[str]:
        return {it.source for it in self.items}

    @property
    def platforms(self) -> Counter:
        return Counter(it.platform for it in self.items)


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    if len(a) > len(b):
        a, b = b, a
    dot = sum(v * b.get(k, 0.0) for k, v in a.items())
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def _add(acc: dict[str, float], vec: dict[str, float]) -> None:
    for k, v in vec.items():
        acc[k] = acc.get(k, 0.0) + v


def _dedupe(items: list[Item]) -> list[Item]:
    seen, out = set(), []
    for it in items:
        key = re.sub(r"\W+", "", it.title.lower())[:80]
        if key and key not in seen:
            seen.add(key)
            out.append(it)
    return out


def _bigrams(tokens: list[str]) -> list[str]:
    return [f"{a} {b}" for a, b in zip(tokens, tokens[1:])]


def _fmt_date(dt: datetime | None) -> str:
    return dt.astimezone().strftime("%d %b %Y") if dt else "?"


def build_issues(
    items: list[Item],
    query: str,
    threshold: float = 0.25,
    max_issues: int = 10,
) -> tuple[list[Issue], Counter]:
    """Kelompokkan item menjadi isu. Mengembalikan (daftar isu, frekuensi kata kunci global)."""
    items = _dedupe(items)
    if not items:
        return [], Counter()

    query_terms = set(tokenize(query))

    # Token per dokumen: judul diberi bobot ganda dibanding cuplikan
    docs = [tokenize(it.title) * 2 + tokenize(it.snippet[:300]) for it in items]

    n = len(docs)
    df = Counter()
    for toks in docs:
        df.update(set(toks))

    def vectorize(toks: list[str]) -> dict[str, float]:
        tf = Counter(toks)
        vec = {}
        for term, cnt in tf.items():
            idf = math.log((n + 1) / (df[term] + 1)) + 1.0
            weight = (1 + math.log(cnt)) * idf
            # Kata tema muncul di hampir semua artikel, kurangi pengaruhnya
            if term in query_terms:
                weight *= 0.2
            vec[term] = weight
        return vec

    vecs = [vectorize(t) for t in docs]

    # Urutkan agar artikel paling "kuat" (Reddit populer, terbaru) jadi benih klaster
    now = datetime.now(timezone.utc)

    def seed_rank(i: int) -> float:
        it = items[i]
        age_h = (now - it.published).total_seconds() / 3600 if it.published else 999
        return math.log1p(it.score + it.comments) + 1 / (1 + age_h / 24)

    order = sorted(range(n), key=seed_rank, reverse=True)

    clusters: list[list[int]] = []
    centroids: list[dict[str, float]] = []
    for i in order:
        best, best_sim = -1, 0.0
        for c, cen in enumerate(centroids):
            sim = _cosine(vecs[i], cen)
            if sim > best_sim:
                best, best_sim = c, sim
        if best >= 0 and best_sim >= threshold:
            clusters[best].append(i)
            _add(centroids[best], vecs[i])
        else:
            clusters.append([i])
            centroids.append(dict(vecs[i]))

    # Bentuk penulisan asli tiap kata (mis. "TKDN", "Wuling") untuk label
    forms: dict[str, Counter] = {}
    for it in items:
        for raw in TOKEN_RE.findall(it.title):
            forms.setdefault(raw.lower(), Counter())[raw] += 1
    display_form = {}
    for low, cnt in forms.items():
        best = cnt.most_common(1)[0][0]
        display_form[low] = best if not best.islower() else best.capitalize()

    global_kw = Counter()
    for toks in docs:
        global_kw.update(t for t in set(toks) if t not in query_terms)

    issues: list[Issue] = []
    for idx, members in enumerate(clusters):
        cen = centroids[idx]
        its = [items[i] for i in members]
        issue = Issue(items=its)

        # Kata kunci: bobot tertinggi di centroid, tanpa kata tema
        kw = sorted(
            ((t, w) for t, w in cen.items() if t not in query_terms),
            key=lambda x: x[1],
            reverse=True,
        )
        issue.keywords = [t for t, _ in kw[:6]]

        # Frasa dua kata yang berulang menjadi label yang lebih alami
        bigram_counts = Counter()
        for i in members:
            title_toks = [t for t in tokenize(items[i].title) if t not in query_terms]
            bigram_counts.update(set(_bigrams(title_toks)))
        common = [bg for bg, c in bigram_counts.most_common(3) if c >= 2]
        if common:
            words = common[0].split()
            words += [k for k in issue.keywords if k not in words][:2]
        else:
            words = issue.keywords[:3]
        issue.label = (
            " · ".join(display_form.get(w, w.title()) for w in words) or items[members[0]].title[:60]
        )

        # Judul paling representatif = paling mirip dengan centroid
        rep = max(members, key=lambda i: _cosine(vecs[i], cen) + 0.05 * math.log1p(items[i].score))
        issue.headline = items[rep]

        # Kalimat pendukung: judul/cuplikan lain yang berbeda dari judul utama
        chosen_vecs = [vecs[rep]]
        for i in sorted(members, key=lambda i: _cosine(vecs[i], cen), reverse=True):
            if i == rep:
                continue
            if all(_cosine(vecs[i], v) < 0.6 for v in chosen_vecs):
                text = items[i].title
                if items[i].platform == "Reddit" and items[i].snippet:
                    first = re.split(r"(?<=[.!?])\s+", items[i].snippet)[0]
                    text = f"{text} — “{first[:200]}”"
                issue.highlights.append(f"{text} ({items[i].source})")
                chosen_vecs.append(vecs[i])
            if len(issue.highlights) >= 3:
                break

        # Skor popularitas
        n_items = len(its)
        n_sources = len(issue.sources)
        engagement = sum(it.score + 2 * it.comments for it in its)
        dates = [it.published for it in its if it.published]
        recency = 0.0
        if dates:
            newest_h = (now - max(dates)).total_seconds() / 3600
            recency = 1 / (1 + newest_h / 24)
        issue.score = round(n_items * 1.0 + n_sources * 1.5 + math.log1p(engagement) * 0.8 + recency * 2, 1)

        # Ringkasan otomatis
        parts = []
        pf = issue.platforms
        counts = []
        if pf.get("Google News"):
            counts.append(f"{pf['Google News']} berita")
        if pf.get("Reddit"):
            counts.append(f"{pf['Reddit']} diskusi Reddit")
        span = ""
        if dates:
            d0, d1 = _fmt_date(min(dates)), _fmt_date(max(dates))
            span = f" pada {d0}" if d0 == d1 else f" antara {d0} dan {d1}"
        parts.append(
            f"Isu ini dibahas dalam {' dan '.join(counts)} dari {n_sources} sumber{span}."
        )
        parts.append(f"Inti pemberitaan: “{issue.headline.title}”.")
        if issue.keywords:
            parts.append("Topik yang sering muncul: " + ", ".join(issue.keywords[:5]) + ".")
        if engagement and pf.get("Reddit"):
            ups = sum(it.score for it in its)
            com = sum(it.comments for it in its)
            parts.append(f"Di Reddit, isu ini mendapat {ups:,} upvote dan {com:,} komentar.")
        issue.summary = " ".join(parts)

        # Urutkan artikel dalam isu: terbaru dulu
        issue.items.sort(
            key=lambda it: it.published or datetime.min.replace(tzinfo=timezone.utc), reverse=True
        )
        issues.append(issue)

    issues.sort(key=lambda x: x.score, reverse=True)
    return issues[:max_issues], global_kw


def issues_to_markdown(issues: list[Issue], query: str, meta: str) -> str:
    lines = [f"# Isu Populer: {query}", "", f"_{meta}_", ""]
    for rank, iss in enumerate(issues, 1):
        lines += [f"## {rank}. {iss.label}  (skor {iss.score})", "", iss.summary, ""]
        if iss.highlights:
            lines.append("**Sorotan lain:**")
            lines += [f"- {h}" for h in iss.highlights]
            lines.append("")
        lines.append("**Sumber:**")
        for it in iss.items[:10]:
            lines.append(f"- [{it.title}]({it.link}) — {it.source}, {_fmt_date(it.published)}")
        lines.append("")
    return "\n".join(lines)
