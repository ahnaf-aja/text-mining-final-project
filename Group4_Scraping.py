"""Scraper berita AI/Generative AI dari detik.com dan cnnindonesia.com.

Jalankan dari folder repo:
  python Group4_Scraping.py index    -> CNN (API + halaman tag) + indeks pencarian Detik
  python Group4_Scraping.py fetch    -> unduh isi artikel Detik yang ada di detik_selected.csv
                                         (detik_selected.csv dibuat oleh notebook 01)
  python Group4_Scraping.py liputan6 -> halaman tag + isi artikel Liputan6

Semua tahap resumable: hasil ditulis bertahap ke scraped/*.jsonl dan permintaan yang sudah selesai
tidak diulang. robots.txt kedua situs mengizinkan user-agent umum (`User-agent: *` / `Allow: /`);
scraper tetap memberi jeda antar permintaan.
"""
import calendar
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent if "__file__" in globals() else Path.cwd()   # folder repo
RAW = ROOT / "scraped"
RAW.mkdir(parents=True, exist_ok=True)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept-Language": "id-ID,id;q=0.9,en;q=0.8"}
DELAY = 0.5          # jeda per permintaan per thread (detik)
WORKERS = int(__import__("os").environ.get("SCRAPE_WORKERS", 4))

# Periode: rilis publik ChatGPT (30 Nov 2022) s.d. 31 Okt 2026
START = (2022, 12)
END = (2026, 10)

KEYWORDS = [
    "AI", "kecerdasan buatan", "artificial intelligence", "ChatGPT", "OpenAI",
    "AI generatif", "generative AI", "Gemini", "Copilot", "DeepSeek",
    "deepfake", "chatbot",
]

_local = threading.local()
_write_lock = threading.Lock()


def session():
    if not hasattr(_local, "s"):
        _local.s = requests.Session()
        _local.s.headers.update(HEADERS)
    return _local.s


def get(url, params=None, tries=4):
    """GET dengan retry + backoff. Mengembalikan Response atau None."""
    for i in range(tries):
        try:
            r = session().get(url, params=params, timeout=30)
            if r.status_code == 200:
                time.sleep(DELAY)
                return r
            if r.status_code in (404, 410):
                return None
            time.sleep(3 * (i + 1))          # 429/5xx -> tunggu lebih lama
        except requests.RequestException:
            time.sleep(3 * (i + 1))
    return None


def append_jsonl(path, rows):
    with _write_lock, open(path, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def read_jsonl(path):
    if not Path(path).exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def months():
    y, m = START
    while (y, m) <= END:
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


# --------------------------------------------------------------------------
# DETIK: halaman pencarian per kata kunci x bulan
# --------------------------------------------------------------------------
DETIK_SEARCH = "https://www.detik.com/search/searchall"


def detik_search_page(keyword, y, m, page):
    last = calendar.monthrange(y, m)[1]
    r = get(DETIK_SEARCH, params={
        "query": keyword, "result_type": "latest",
        "fromdatex": f"01/{m:02d}/{y}", "todatex": f"{last:02d}/{m:02d}/{y}",
        "page": page,
    })
    if r is None:
        return []
    soup = BeautifulSoup(r.text, "lxml")
    rows = []
    for art in soup.select("article.list-content__item"):
        a = art.select_one("h3.media__title a") or art.select_one("a.media__link")
        if not a or not a.get("href"):
            continue
        ts = art.select_one("[d-time]")
        sub = art.select_one(".media__subtitle")
        desc = art.select_one(".media__desc")
        rows.append({
            "source": "detik",
            "url": a["href"].split("?")[0],
            "title": a.get_text(" ", strip=True),
            "channel": sub.get_text(" ", strip=True) if sub else "",
            "desc": desc.get_text(" ", strip=True) if desc else "",
            "timestamp": int(ts["d-time"]) if ts and ts.get("d-time", "").isdigit() else None,
            "keyword": keyword,
        })
    return rows


def detik_index_month(keyword, y, m, max_pages=120):
    out, page = [], 1
    while page <= max_pages:
        rows = detik_search_page(keyword, y, m, page)
        if not rows:
            break
        out.extend(rows)
        page += 1
    return out


def run_detik_index():
    path = RAW / "detik_index.jsonl"
    done_path = RAW / "detik_index_done.txt"
    done = set(done_path.read_text(encoding="utf-8").split("\n")) if done_path.exists() else set()
    jobs = [(k, y, m) for k in KEYWORDS for (y, m) in months() if f"{k}|{y}-{m:02d}" not in done]
    print(f"[detik index] {len(jobs)} job (kata kunci x bulan) tersisa", flush=True)
    n = 0
    with ThreadPoolExecutor(WORKERS) as ex:
        futs = {ex.submit(detik_index_month, *j): j for j in jobs}
        for i, fut in enumerate(as_completed(futs), 1):
            k, y, m = futs[fut]
            rows = fut.result()
            append_jsonl(path, rows)
            with _write_lock, open(done_path, "a", encoding="utf-8") as f:
                f.write(f"{k}|{y}-{m:02d}\n")
            n += len(rows)
            if i % 20 == 0 or i == len(jobs):
                print(f"  {i}/{len(jobs)} job, +{n} baris", flush=True)


# --------------------------------------------------------------------------
# CNN INDONESIA: API pencarian (mengembalikan isi artikel lengkap)
# --------------------------------------------------------------------------
CNN_API = "https://www.cnnindonesia.com/api/v3/search"


def html_to_text(html):
    soup = BeautifulSoup(html or "", "lxml")
    for t in soup(["script", "style", "table", "iframe", "figure"]):
        t.decompose()
    paras = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
    paras = [p for p in paras if p]
    return "\n".join(paras) if paras else soup.get_text(" ", strip=True)


def run_cnn():
    path = RAW / "cnn_articles.jsonl"
    seen = {r["url"] for r in read_jsonl(path)}
    for kw in KEYWORDS:
        start, got = 0, 0
        while True:
            r = get(CNN_API, params={"query": kw, "idtype": 1, "start": start,
                                     "limit": 50, "pageType": "search"})
            data = (r.json().get("data") or []) if r is not None else []
            if not data:
                break
            rows = []
            for d in data:
                url = d.get("url") or ""
                if not url or url in seen:
                    continue
                seen.add(url)
                rows.append({
                    "source": "cnn",
                    "url": url,
                    "title": d.get("strjudul", ""),
                    "channel": url.split("/")[3] if url.count("/") > 3 else "",
                    "subchannel": d.get("strnmkanal", ""),
                    "desc": d.get("strringkasan", ""),
                    "date": (d.get("dtnewsdate") or "").replace("/", "-"),
                    "tags": d.get("strtag", ""),
                    "body": html_to_text(d.get("strisi", "")),
                    "keyword": kw,
                })
            append_jsonl(path, rows)
            got += len(rows)
            start += 50
        print(f"[cnn] '{kw}': +{got} artikel baru (total {len(seen)})", flush=True)


# --------------------------------------------------------------------------
# CNN INDONESIA: halaman tag (API pencarian hanya menjangkau +-1 tahun terakhir,
# halaman tag menjangkau sampai awal 2023) + isi artikel
# --------------------------------------------------------------------------
CNN_TAGS = ["kecerdasan-buatan", "ai", "artificial-intelligence", "chatgpt", "openai", "chatbot",
            "deepfake", "gemini", "deepseek", "teknologi-ai", "generative-ai", "ai-generatif",
            "copilot", "google-gemini", "sam-altman", "nvidia"]
CNN_URL_RE = re.compile(r"cnnindonesia\.com/([a-z-]+)/(20\d{12})-\d+-\d+/")


def cnn_tag_pages(tag, max_pages=400):
    out, page, empty = [], 1, 0
    while page <= max_pages and empty < 2:
        r = get(f"https://www.cnnindonesia.com/tag/{tag}", params={"page": page})
        rows = []
        if r is not None:
            soup = BeautifulSoup(r.text, "lxml")
            for a in soup.select("article a[href]"):
                m = CNN_URL_RE.search(a["href"])
                h = a.select_one("h2")
                if m and h:
                    rows.append({"source": "cnn", "url": a["href"].split("?")[0],
                                 "title": h.get_text(" ", strip=True), "channel": m.group(1), "tag": tag})
        empty = empty + 1 if not rows else 0
        out.extend(rows)
        page += 1
    return out


def run_cnn_tags():
    path = RAW / "cnn_tag_index.jsonl"
    done = {r["tag"] for r in read_jsonl(path)}
    with ThreadPoolExecutor(WORKERS) as ex:
        futs = {ex.submit(cnn_tag_pages, t): t for t in CNN_TAGS if t not in done}
        for fut in as_completed(futs):
            rows = fut.result()
            append_jsonl(path, rows)
            print(f"[cnn tag] {futs[fut]}: {len(rows)} tautan", flush=True)


def cnn_article(row):
    r = get(row["url"])
    if r is None:
        return {**row, "ok": False}
    soup = BeautifulSoup(r.text, "lxml")
    body = soup.select_one(".detail-text")
    if body is None:
        return {**row, "ok": False}
    for t in body.select("script, style, table, iframe, figure, .paradetail, .para_caption"):
        t.decompose()
    paras = [p.get_text(" ", strip=True) for p in body.find_all("p")]

    def meta(name):
        t = soup.find("meta", attrs={"name": name})
        return t.get("content", "") if t else ""

    return {**row, "ok": True, "desc": meta("description"),
            "date": meta("publishdate").replace("/", "-"), "tags": meta("keywords"),
            "subchannel": meta("dtk:namakanal"), "body": "\n".join(p for p in paras if p), "keyword": "tag:" + row["tag"]}


def run_cnn_fetch():
    path = RAW / "cnn_articles.jsonl"
    have = {r["url"] for r in read_jsonl(path)}
    todo = {}
    for r in read_jsonl(RAW / "cnn_tag_index.jsonl"):
        if r["url"] not in have and "/tv/" not in r["url"]:
            todo.setdefault(r["url"], r)
    print(f"[cnn fetch] {len(todo)} artikel dari halaman tag belum ada", flush=True)
    with ThreadPoolExecutor(WORKERS) as ex:
        futs = [ex.submit(cnn_article, r) for r in todo.values()]
        for i, fut in enumerate(as_completed(futs), 1):
            res = fut.result()
            if res.get("ok"):
                res.pop("ok"); res.pop("tag", None)
                append_jsonl(path, [res])
            if i % 250 == 0 or i == len(futs):
                print(f"  {i}/{len(futs)}", flush=True)


# --------------------------------------------------------------------------
# DETIK: isi artikel
# --------------------------------------------------------------------------
def detik_article(url):
    r = get(url, params={"single": 1})
    if r is None:
        return {"url": url, "ok": False}
    soup = BeautifulSoup(r.text, "lxml")
    body = soup.select_one(".detail__body-text") or soup.select_one(".itp_bodycontent")
    if body is None:
        return {"url": url, "ok": False}
    for t in body.select("script, style, table, iframe, .aevp, .embed, .detail__body-tag, "
                         ".ads-scrollpage-container, .lihatjg, .sisip_embed_sosmed, .staticdetail_container"):
        t.decompose()
    paras = [p.get_text(" ", strip=True) for p in body.find_all("p")]
    paras = [p for p in paras if p]
    h1 = soup.select_one("h1")

    def meta(name):
        t = soup.find("meta", attrs={"name": name})
        return t.get("content", "") if t else ""

    return {
        "url": url, "ok": True,
        "title_page": h1.get_text(" ", strip=True) if h1 else "",
        "date": meta("publishdate").replace("/", "-"),
        "kanalid": meta("kanalid"),
        "author": meta("author"),
        "tags": meta("keywords"),
        "body": "\n".join(paras),
    }


def run_detik_fetch():
    sel = pd.read_csv(ROOT / "detik_selected.csv")
    path = RAW / "detik_articles.jsonl"
    done = {r["url"] for r in read_jsonl(path)}
    urls = [u for u in sel["url"].tolist() if u not in done]
    print(f"[detik fetch] {len(urls)} artikel tersisa dari {len(sel)}", flush=True)
    with ThreadPoolExecutor(WORKERS) as ex:
        futs = [ex.submit(detik_article, u) for u in urls]
        for i, fut in enumerate(as_completed(futs), 1):
            append_jsonl(path, [fut.result()])
            if i % 250 == 0 or i == len(urls):
                print(f"  {i}/{len(urls)}", flush=True)


# --------------------------------------------------------------------------
# LIPUTAN6: halaman tag (robots.txt mengizinkan /tag/, melarang /search) + isi artikel.
# Catatan: Antara tidak dipakai karena setiap artikelnya mencantumkan larangan crawling/pengindeksan
# otomatis untuk AI tanpa izin tertulis, walaupun robots.txt-nya mengizinkan.
# --------------------------------------------------------------------------
L6_TAGS = ["kecerdasan-buatan", "artificial-intelligence", "ai", "chatgpt", "openai", "deepfake", "chatbot",
           "generative-ai", "ai-generatif", "gemini-ai", "deepseek", "teknologi-ai", "google-gemini", "copilot"]
L6_URL_RE = re.compile(r"https://www\.liputan6\.com/([a-z0-9-]+)/read/(\d+)/[^?#\"]+")


def l6_tag_pages(tag, max_pages=60):
    out, page = [], 1
    while page <= max_pages:
        r = get(f"https://www.liputan6.com/tag/{tag}", params={"page": page})
        if r is None:                       # 404 = melewati halaman terakhir
            break
        soup = BeautifulSoup(r.content, "lxml")
        main = soup.select_one("div.tags--layout--right_all")
        rows = []
        for item in (main.select("article.articles--iridescent-list--item") if main else []):
            a = item.select_one("a[href*='/read/']")
            m = L6_URL_RE.search(a["href"]) if a else None
            if not m:
                continue
            t = item.select_one("time[datetime]")
            title = item.select_one("[class*=title]")
            rows.append({"source": "liputan6", "url": m.group(0), "channel": m.group(1), "tag": tag,
                         "title": (title or a).get_text(" ", strip=True),
                         "date": t["datetime"][:19].replace("T", " ") if t else ""})
        if not rows:
            break
        out.extend(rows)
        page += 1
    return out


def run_l6_index():
    path = RAW / "liputan6_index.jsonl"
    done = {r["tag"] for r in read_jsonl(path)}
    with ThreadPoolExecutor(WORKERS) as ex:
        futs = {ex.submit(l6_tag_pages, t): t for t in L6_TAGS if t not in done}
        for fut in as_completed(futs):
            rows = fut.result()
            append_jsonl(path, rows)
            print(f"[liputan6 tag] {futs[fut]}: {len(rows)} tautan", flush=True)


def l6_article(row):
    r = get(row["url"])
    if r is None:
        return {**row, "ok": False}
    soup = BeautifulSoup(r.content, "lxml")
    blocks = soup.select(".article-content-body__item-content")
    if not blocks:
        return {**row, "ok": False}
    paras = []
    for blk in blocks:
        for t in blk.select("script, style, table, iframe, figure, .baca-juga, .advertisement"):
            t.decompose()
        paras += [p.get_text(" ", strip=True) for p in blk.find_all("p")]

    def meta(name):
        t = soup.find("meta", attrs={"name": name}) or soup.find("meta", attrs={"property": name})
        return t.get("content", "") if t else ""

    return {**row, "ok": True, "desc": meta("description"), "tags": meta("keywords"),
            "date": meta("article:published_time")[:19].replace("T", " ") or row.get("date", ""),
            "body": "\n".join(p for p in paras if p), "keyword": "tag:" + row["tag"]}


def run_l6_fetch():
    todo = {}
    for r in read_jsonl(RAW / "liputan6_index.jsonl"):
        todo.setdefault(r["url"], r)
    path = RAW / "liputan6_articles.jsonl"
    have = {r["url"] for r in read_jsonl(path)}
    rows = [r for u, r in todo.items() if u not in have]
    print(f"[liputan6 fetch] {len(rows)} artikel tersisa dari {len(todo)}", flush=True)
    with ThreadPoolExecutor(WORKERS) as ex:
        futs = [ex.submit(l6_article, r) for r in rows]
        for i, fut in enumerate(as_completed(futs), 1):
            res = fut.result()
            res.pop("tag", None)
            append_jsonl(path, [res])
            if i % 250 == 0 or i == len(rows):
                print(f"  {i}/{len(rows)}", flush=True)


if __name__ == "__main__":
    step = sys.argv[1] if len(sys.argv) > 1 else "index"
    if step == "index":
        run_cnn()
        run_cnn_tags()
        run_cnn_fetch()
        run_detik_index()
    elif step == "fetch":
        run_detik_fetch()
    elif step == "liputan6":
        run_l6_index()
        run_l6_fetch()
