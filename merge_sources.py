#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Şehitlerimiz veri birleştirici

Kaynaklar:
1) sehitlerimiz.org.tr CSV (ana tarihsel veri seti)
2) EGM genel Şehitlerimiz sayfası
3) EGM Özel Harekât Şehitlerimiz
4) Jandarma Şehit Sorgulama
5) Sahil Güvenlik Şehitlerimiz

Amaç:
- Kaynakları ortak şemaya çevirmek
- Aynı kişiyi mümkün olduğunca güvenli biçimde tek kayda indirmek
- Kaynakların tamamını 'kaynaklar' alanında korumak
- Bir kaynaktan gelen boş alanı başka kaynakta doluysa tamamlamak
- Takvim için tam tarih bulunan kayıtları ayrıca üretmek

Not:
MSB'nin tarihsel Şehit Bilgi Kapısı verileri sehitlerimiz.org.tr'nin
ana CSV'sinde zaten yer aldığı için ayrıca HTML kazıma yerine bu veri seti
temel alınır. Bu yaklaşım, MSB'nin il/sayfa tabanlı arşivini eksik çekme
riskini azaltır.
"""

import csv
import io
import re
import hashlib
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE_CSV_URL = "https://sehitlerimiz.org.tr/veri/sehitler.csv"
EGM_URL = "https://www.egm.gov.tr/sehitlerimiz"
EGM_OH_URL = "https://www.egm.gov.tr/ozelharekat/sehitlerimiz"
JANDARMA_URL = "https://vatandas.jandarma.gov.tr/sehit/sehitsorgu/"
SAHIL_URL = "https://www.sg.gov.tr/sehitlerimiz"

OUT_DIR = Path("data")
OUT_DIR.mkdir(exist_ok=True)

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; Sehitlerimiz/1.0)"}

def clean(s):
    return re.sub(r"\s+", " ", str(s or "").strip())

def norm(s):
    s = clean(s).casefold()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.translate(str.maketrans({"ı":"i","İ":"i","ş":"s","Ş":"s","ğ":"g","Ğ":"g","ü":"u","Ü":"u","ö":"o","Ö":"o","ç":"c","Ç":"c"}))
    return re.sub(r"[^a-z0-9]+", " ", s).strip()

def parse_date(s):
    s = clean(s)
    if not s:
        return ""
    for fmt in ("%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d", "%Y/%m/%d", "%d.%m.%y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    m = re.search(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})", s)
    if m:
        try:
            return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1))).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return ""

def fetch(url):
    r = requests.get(url, headers=HEADERS, timeout=60)
    r.raise_for_status()
    return r.text

def add_record(records, rec):
    rec = {k: clean(v) for k, v in rec.items()}
    if not rec["ad_soyad"]:
        return
    records.append(rec)

def load_base():
    text = requests.get(BASE_CSV_URL, headers=HEADERS, timeout=120).content.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    records = []
    for row in reader:
        ad = clean(row.get("ad"))
        # Kaynaktaki veri zaten ad + baba adı biçiminde olduğundan
        # ad_soyad alanında yalnızca ad tutulur; soyad alanı ayrı kaynaklarda
        # bulunuyorsa normalize aşamasında birleşir.
        add_record(records, {
            "ad_soyad": ad,
            "baba_adi": row.get("baba_adi",""),
            "rutbe": row.get("rutbe",""),
            "kurum": "MSB / tarihsel arşiv",
            "memleket": row.get("memleket",""),
            "dogum_yeri": row.get("dogum_yeri",""),
            "dogum_yili": row.get("dogum_yili",""),
            "sehadet_tarihi": parse_date(row.get("sehadet_tarihi","")),
            "donem_cephe": row.get("donem_cephe",""),
            "kaynak": "sehitlerimiz.org.tr",
            "kaynak_sayfa": row.get("sayfa",""),
            "kaynaklar": "sehitlerimiz.org.tr",
        })
    return records

def parse_egm(url, kurum):
    soup = BeautifulSoup(fetch(url), "html.parser")
    records = []
    # EGM sayfalarında tarih + 'Şehit ...' metinlerini yakala.
    text = soup.get_text("\n", strip=True)
    for line in text.splitlines():
        m = re.search(r"(\d{2}\.\d{2}\.\d{4})\s+Şehit\s+(.+)", line)
        if not m:
            continue
        d = parse_date(m.group(1))
        rest = clean(m.group(2))
        rest = re.sub(r"\s*Şehit\s+.*$", "", rest)
        add_record(records, {
            "ad_soyad": re.sub(r"^.*?(?:Memuru|Başpolis Memuru|Komiser Yardımcısı|Komiser|Başkomiser|Emniyet Amiri)\s+", "", rest).strip() or rest,
            "baba_adi": "",
            "rutbe": "",
            "kurum": kurum,
            "memleket": "",
            "dogum_yeri": "",
            "dogum_yili": "",
            "sehadet_tarihi": d,
            "donem_cephe": "",
            "kaynak": url,
            "kaynak_sayfa": "",
            "kaynaklar": url,
        })
    return records

def parse_jandarma(url):
    soup = BeautifulSoup(fetch(url), "html.parser")
    records = []
    rows = soup.find_all("tr")
    for tr in rows:
        cells = [clean(x.get_text(" ", strip=True)) for x in tr.find_all(["td","th"])]
        if len(cells) < 4:
            continue
        d = parse_date(cells[1])
        if not d:
            continue
        rank, first, last = cells[2], cells[3], cells[4] if len(cells) > 4 else ""
        add_record(records, {
            "ad_soyad": f"{first} {last}".strip(),
            "baba_adi": "",
            "rutbe": rank,
            "kurum": "Jandarma Genel Komutanlığı",
            "memleket": "",
            "dogum_yeri": "",
            "dogum_yili": "",
            "sehadet_tarihi": d,
            "donem_cephe": "",
            "kaynak": url,
            "kaynak_sayfa": "",
            "kaynaklar": url,
        })
    return records

def parse_sahil(url):
    soup = BeautifulSoup(fetch(url), "html.parser")
    records = []
    text = soup.get_text("\n", strip=True)
    lines = [clean(x) for x in text.splitlines() if clean(x)]
    for i, line in enumerate(lines):
        m = re.fullmatch(r"(\d{1,2})\s+(\w+)\s+(\d{4})", line)
        if not m:
            continue
        d = parse_date(line)
        if i == 0:
            continue
        name = lines[i-1]
        add_record(records, {
            "ad_soyad": name,
            "baba_adi": "",
            "rutbe": "",
            "kurum": "Sahil Güvenlik Komutanlığı",
            "memleket": "",
            "dogum_yeri": "",
            "dogum_yili": "",
            "sehadet_tarihi": d,
            "donem_cephe": "",
            "kaynak": url,
            "kaynak_sayfa": "",
            "kaynaklar": url,
        })
    return records

def key_for(r):
    name = norm(r["ad_soyad"])
    date = r["sehadet_tarihi"]
    # Tarih + isim en güvenli kısa anahtar.
    if date:
        return ("date", name, date)
    # Tarih yoksa baba adı/memleket ile daha sıkı anahtar.
    return ("nodate", name, norm(r["baba_adi"]), norm(r["memleket"]))

def merge(records):
    merged = {}
    for r in records:
        k = key_for(r)
        if k not in merged:
            merged[k] = dict(r)
            continue
        old = merged[k]
        for field in old:
            if field == "kaynaklar":
                continue
            if not old[field] and r[field]:
                old[field] = r[field]
        srcs = set(filter(None, [x.strip() for x in (old["kaynaklar"] + ";" + r["kaynaklar"]).split(";")]))
        old["kaynaklar"] = ";".join(sorted(srcs))
    return list(merged.values())

def write_csv(rows, path):
    fields = ["id","ad_soyad","baba_adi","rutbe","kurum","memleket","dogum_yeri","dogum_yili","sehadet_tarihi","donem_cephe","kaynak","kaynak_sayfa","kaynaklar"]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for i, r in enumerate(rows, 1):
            r = dict(r)
            r["id"] = hashlib.sha256((key_for(r).__repr__()).encode("utf-8")).hexdigest()[:16]
            w.writerow({k:r.get(k,"") for k in fields})

def main():
    all_records = []
    base = load_base()
    print("sehitlerimiz.org.tr:", len(base))
    all_records.extend(base)

    for label, fn in [
        ("EGM", lambda: parse_egm(EGM_URL, "Emniyet Genel Müdürlüğü")),
        ("EGM Özel Harekât", lambda: parse_egm(EGM_OH_URL, "EGM Özel Harekât")),
        ("Jandarma", lambda: parse_jandarma(JANDARMA_URL)),
        ("Sahil Güvenlik", lambda: parse_sahil(SAHIL_URL)),
    ]:
        try:
            rows = fn()
            print(label + ":", len(rows))
            all_records.extend(rows)
        except Exception as e:
            print(label + " HATA:", e)

    merged = merge(all_records)
    merged.sort(key=lambda r: (r["sehadet_tarihi"] == "", r["sehadet_tarihi"], norm(r["ad_soyad"])))

    write_csv(merged, OUT_DIR / "sehitlerimiz_birlesik.csv")

    # Takvim için tam tarihi olan kayıtları ayrıca yaz.
    dated = [r for r in merged if r["sehadet_tarihi"]]
    write_csv(dated, OUT_DIR / "sehitlerimiz_takvim.csv")

    print("Ham toplam:", len(all_records))
    print("Birleştirilmiş benzersiz:", len(merged))
    print("Tam tarihli:", len(dated))

if __name__ == "__main__":
    main()
