#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import csv
import io
import re
import sys
import hashlib
import unicodedata
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://sehitlerimiz.org.tr/veri/sehitler.csv"

SOURCES = {
    "EGM": "https://www.egm.gov.tr/sehitlerimiz",
    "EGM_OZEL_HAREKAT": "https://www.egm.gov.tr/ozelharekat/sehitlerimiz",
    "EGM_HAVACILIK": "https://www.egm.gov.tr/havacilik/sehitlerimiz",
    "JANDARMA": "https://vatandas.jandarma.gov.tr/sehit/sehitsorgu/",
    "SAHIL_GUVENLIK": "https://www.sg.gov.tr/sehitlerimiz",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 Chrome/140 Safari/537.36",
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
}

OUT = Path("data")
OUT.mkdir(exist_ok=True)

FIELDS = [
    "id",
    "ad_soyad",
    "baba_adi",
    "rutbe",
    "kurum",
    "memleket",
    "dogum_yeri",
    "dogum_yili",
    "sehadet_tarihi",
    "donem_cephe",
    "kaynaklar",
]


def clean(x):
    return re.sub(r"\s+", " ", str(x or "")).strip()


def normalize(x):
    x = clean(x).casefold()

    x = unicodedata.normalize("NFKD", x)
    x = "".join(
        c for c in x
        if not unicodedata.combining(c)
    )

    table = str.maketrans({
        "ı": "i",
        "ş": "s",
        "ğ": "g",
        "ü": "u",
        "ö": "o",
        "ç": "c",
    })

    x = x.translate(table)

    return re.sub(r"[^a-z0-9]+", " ", x).strip()


def parse_date(value):
    value = clean(value)

    if not value:
        return ""

    formats = [
        "%d.%m.%Y",
        "%d/%m/%Y",
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%d-%m-%Y",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass

    m = re.search(
        r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})",
        value
    )

    if m:
        try:
            return datetime(
                int(m.group(3)),
                int(m.group(2)),
                int(m.group(1))
            ).strftime("%Y-%m-%d")
        except ValueError:
            pass

    return ""


def request(url):
    response = requests.get(
        url,
        headers=HEADERS,
        timeout=90
    )

    response.raise_for_status()

    return response


def base_source():
    print("BASE:", BASE_URL)

    response = request(BASE_URL)

    text = response.content.decode(
        "utf-8-sig",
        errors="replace"
    )

    reader = csv.DictReader(
        io.StringIO(text)
    )

    rows = []

    for row in reader:

        name = clean(row.get("ad"))

        if not name:
            continue

        rows.append({
            "ad_soyad": name,
            "baba_adi": clean(row.get("baba_adi")),
            "rutbe": clean(row.get("rutbe")),
            "kurum": "sehitlerimiz.org.tr",
            "memleket": clean(row.get("memleket")),
            "dogum_yeri": clean(row.get("dogum_yeri")),
            "dogum_yili": clean(row.get("dogum_yili")),
            "sehadet_tarihi": parse_date(
                row.get("sehadet_tarihi")
            ),
            "donem_cephe": clean(
                row.get("donem_cephe")
            ),
            "kaynaklar":
                "sehitlerimiz.org.tr",
        })

    print("BASE KAYIT:", len(rows))

    if len(rows) < 100000:
        raise RuntimeError(
            "Ana kaynak beklenenden az kayıt döndürdü!"
        )

    return rows


def extract_date_name_pairs(text):
    """
    Genel sayfalarda:

        14.06.2026
        Tayfun BAŞ
        Polis Memuru

    veya:

        Tayfun BAŞ
        14 Haziran 2026

    gibi yapılardan tarih + isim çıkarmaya çalışır.
    """

    lines = [
        clean(x)
        for x in text.splitlines()
        if clean(x)
    ]

    results = []

    months = (
        "ocak|şubat|mart|nisan|mayıs|haziran|"
        "temmuz|ağustos|eylül|ekim|kasım|aralık"
    )

    month_re = re.compile(
        rf"(\d{{1,2}})\s+({months})\s+(\d{{4}})",
        re.I
    )

    numeric_re = re.compile(
        r"\b(\d{1,2}[./]\d{1,2}[./]\d{4})\b"
    )

    for i, line in enumerate(lines):

        date_value = parse_date(line)

        if not date_value:

            m = month_re.search(line)

            if m:
                month_names = {
                    "ocak": 1,
                    "şubat": 2,
                    "mart": 3,
                    "nisan": 4,
                    "mayıs": 5,
                    "haziran": 6,
                    "temmuz": 7,
                    "ağustos": 8,
                    "eylül": 9,
                    "ekim": 10,
                    "kasım": 11,
                    "aralık": 12,
                }

                try:
                    d = int(m.group(1))
                    mo = month_names[m.group(2).casefold()]
                    y = int(m.group(3))

                    date_value = datetime(
                        y, mo, d
                    ).strftime("%Y-%m-%d")

                except Exception:
                    date_value = ""

        if not date_value:
            continue

        candidates = []

        for offset in range(1, 5):

            if i - offset >= 0:
                candidates.append(
                    lines[i - offset]
                )

            if i + offset < len(lines):
                candidates.append(
                    lines[i + offset]
                )

        for candidate in candidates:

            candidate = clean(candidate)

            if len(candidate) < 4:
                continue

            if parse_date(candidate):
                continue

            if re.search(
                r"(şehit|tarih|sayfa|liste|arama|"
                r"komutanlığı|başkanlığı)",
                candidate,
                re.I
            ):
                continue

            # URL / menü / teknik metinleri ele.
            if "http" in candidate.lower():
                continue

            # İsimlerde rakam bulunmasın.
            if re.search(r"\d", candidate):
                continue

            results.append(
                (
                    candidate,
                    date_value
                )
            )

            break

    return results


def scrape_general(url, institution):
    print("TARANIYOR:", institution)

    response = request(url)

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    # Önce bağlantılı bireysel şehit sayfalarını topla.
    links = []

    for a in soup.find_all("a", href=True):

        href = a.get("href", "")
        text = clean(a.get_text(" ", strip=True))

        if not text:
            continue

        if (
            "sehit" in href.lower()
            or "şehit" in href.lower()
            or "sehit" in text.lower()
            or "şehit" in text.lower()
        ):
            links.append(
                (
                    text,
                    href
                )
            )

    # Aynı linkleri temizle.
    unique_links = []
    seen = set()

    for text, href in links:

        if href in seen:
            continue

        seen.add(href)

        if href.startswith("/"):
            href = "https://www.egm.gov.tr" + href

        elif href.startswith("//"):
            href = "https:" + href

        elif not href.startswith("http"):
            continue

        unique_links.append(
            (text, href)
        )

    records = []

    # Sayfanın kendisinden de çıkar.
    pairs = extract_date_name_pairs(
        soup.get_text("\n")
    )

    for name, death in pairs:

        records.append({
            "ad_soyad": name,
            "baba_adi": "",
            "rutbe": "",
            "kurum": institution,
            "memleket": "",
            "dogum_yeri": "",
            "dogum_yili": "",
            "sehadet_tarihi": death,
            "donem_cephe": "",
            "kaynaklar": url,
        })

    # Bireysel sayfaları oku.
    for index, (_, link) in enumerate(
        unique_links[:2000],
        1
    ):

        try:
            r = request(link)

            page = BeautifulSoup(
                r.text,
                "html.parser"
            )

            text = page.get_text("\n")

            pairs = extract_date_name_pairs(text)

            for name, death in pairs:

                records.append({
                    "ad_soyad": name,
                    "baba_adi": "",
                    "rutbe": "",
                    "kurum": institution,
                    "memleket": "",
                    "dogum_yeri": "",
                    "dogum_yili": "",
                    "sehadet_tarihi": death,
                    "donem_cephe": "",
                    "kaynaklar": link,
                })

        except Exception as e:
            print(
                "UYARI:",
                institution,
                link,
                e
            )

    # Aynı kurum içinde duplicate temizle.
    cleaned = {}
    for r in records:

        if not r["ad_soyad"]:
            continue

        key = (
            normalize(r["ad_soyad"]),
            r["sehadet_tarihi"]
        )

        if key not in cleaned:
            cleaned[key] = r

    result = list(cleaned.values())

    print(
        institution,
        "KAYIT:",
        len(result)
    )

    return result


def scrape_jandarma():
    """
    Jandarma sayfasının HTML yapısı değişebildiği için
    mevcut sayfadan alınabilen kayıtları toplar.
    """

    print("TARANIYOR: JANDARMA")

    response = request(
        SOURCES["JANDARMA"]
    )

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    records = []

    # Tablolar
    for tr in soup.find_all("tr"):

        cells = [
            clean(td.get_text(" ", strip=True))
            for td in tr.find_all(
                ["td", "th"]
            )
        ]

        if len(cells) < 2:
            continue

        date_value = ""

        for cell in cells:
            date_value = parse_date(cell)

            if date_value:
                break

        if not date_value:
            continue

        # Tarih dışındaki en anlamlı metni isim olarak al.
        candidates = [
            c for c in cells
            if c != date_value
            and len(c) > 2
        ]

        if not candidates:
            continue

        name = candidates[-1]

        records.append({
            "ad_soyad": name,
            "baba_adi": "",
            "rutbe": "",
            "kurum": "Jandarma Genel Komutanlığı",
            "memleket": "",
            "dogum_yeri": "",
            "dogum_yili": "",
            "sehadet_tarihi": date_value,
            "donem_cephe": "",
            "kaynaklar": SOURCES["JANDARMA"],
        })

    print(
        "JANDARMA KAYIT:",
        len(records)
    )

    return records


def scrape_sahil():
    print("TARANIYOR: SAHİL GÜVENLİK")

    response = request(
        SOURCES["SAHIL_GUVENLIK"]
    )

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    text = soup.get_text("\n")

    pairs = extract_date_name_pairs(text)

    records = []

    for name, death in pairs:

        records.append({
            "ad_soyad": name,
            "baba_adi": "",
            "rutbe": "",
            "kurum": "Sahil Güvenlik Komutanlığı",
            "memleket": "",
            "dogum_yeri": "",
            "dogum_yili": "",
            "sehadet_tarihi": death,
            "donem_cephe": "",
            "kaynaklar":
                SOURCES["SAHIL_GUVENLIK"],
        })

    # Sahil Güvenlik sayfasında isim + tarih blokları
    # olduğu için ikinci güvenlik taraması:
    lines = [
        clean(x)
        for x in text.splitlines()
        if clean(x)
    ]

    for i, line in enumerate(lines):

        d = parse_date(line)

        if not d:
            continue

        if i == 0:
            continue

        # Önceki 3 satırda isim ara.
        for off in range(1, 4):

            if i - off < 0:
                continue

            name = lines[i-off]

            if (
                len(name) >= 4
                and not re.search(r"\d", name)
                and not parse_date(name)
            ):
                records.append({
                    "ad_soyad": name,
                    "baba_adi": "",
                    "rutbe": "",
                    "kurum": "Sahil Güvenlik Komutanlığı",
                    "memleket": "",
                    "dogum_yeri": "",
                    "dogum_yili": "",
                    "sehadet_tarihi": d,
                    "donem_cephe": "",
                    "kaynaklar":
                        SOURCES["SAHIL_GUVENLIK"],
                })
                break

    print(
        "SAHİL GÜVENLİK KAYIT:",
        len(records)
    )

    return records


def merge(all_records):
    """
    Amaç:
    - Tarih + isim eşleşmesini güçlü kabul etmek.
    - Tarih yoksa sadece isimle birleştirmemek.
    - Bir kaynağın boş alanını diğer kaynak doldurabiliyorsa doldurmak.
    """

    result = {}

    for r in all_records:

        name = normalize(
            r["ad_soyad"]
        )

        death = r["sehadet_tarihi"]

        if not name:
            continue

        if death:
            key = (
                name,
                death
            )
        else:
            key = (
                name,
                normalize(r["baba_adi"]),
                normalize(r["memleket"]),
                normalize(r["kurum"])
            )

        if key not in result:

            result[key] = dict(r)

            continue

        old = result[key]

        for field in [
            "baba_adi",
            "rutbe",
            "kurum",
            "memleket",
            "dogum_yeri",
            "dogum_yili",
            "sehadet_tarihi",
            "donem_cephe",
        ]:

            if (
                not old.get(field)
                and r.get(field)
            ):
                old[field] = r[field]

        sources = set(
            filter(
                None,
                (
                    old["kaynaklar"] +
                    ";" +
                    r["kaynaklar"]
                ).split(";")
            )
        )

        old["kaynaklar"] = ";".join(
            sorted(sources)
        )

    return list(result.values())


def write_csv(rows, filename):
    path = OUT / filename

    with path.open(
        "w",
        encoding="utf-8-sig",
        newline=""
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=FIELDS
        )

        writer.writeheader()

        for row in rows:

            source_key = "|".join([
                normalize(row["ad_soyad"]),
                row["sehadet_tarihi"],
                normalize(row["baba_adi"]),
                normalize(row["memleket"]),
            ])

            row_id = hashlib.sha256(
                source_key.encode("utf-8")
            ).hexdigest()[:20]

            output = dict(row)
            output["id"] = row_id

            writer.writerow({
                field:
                    output.get(field, "")
                for field in FIELDS
            })

    return path


def main():

    all_records = []

    base = base_source()
    all_records.extend(base)

    # EGM genel
    all_records.extend(
        scrape_general(
            SOURCES["EGM"],
            "Emniyet Genel Müdürlüğü"
        )
    )

    # EGM Özel Harekât
    all_records.extend(
        scrape_general(
            SOURCES["EGM_OZEL_HAREKAT"],
            "EGM Özel Harekât"
        )
    )

    # EGM Havacılık
    all_records.extend(
        scrape_general(
            SOURCES["EGM_HAVACILIK"],
            "EGM Havacılık"
        )
    )

    # Jandarma
    all_records.extend(
        scrape_jandarma()
    )

    # Sahil Güvenlik
    all_records.extend(
        scrape_sahil()
    )

    merged = merge(
        all_records
    )

    merged.sort(
        key=lambda x: (
            x["sehadet_tarihi"] == "",
            x["sehadet_tarihi"],
            normalize(x["ad_soyad"])
        )
    )

    dated = [
        r for r in merged
        if r["sehadet_tarihi"]
    ]

    all_path = write_csv(
        merged,
        "sehitlerimiz_birlesik.csv"
    )

    calendar_path = write_csv(
        dated,
        "sehitlerimiz_takvim.csv"
    )

    print()
    print("===================================")
    print("SONUÇ")
    print("===================================")
    print("Ham toplam:", len(all_records))
    print("Birleşik benzersiz:", len(merged))
    print("Tam tarihli:", len(dated))
    print("Tüm veri:", all_path)
    print("Takvim verisi:", calendar_path)
    print("===================================")


if __name__ == "__main__":
    main()
