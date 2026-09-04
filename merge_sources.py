#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import csv
import io
import re
import hashlib
import unicodedata
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

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
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/140.0 Safari/537.36"
    ),
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


# ---------------------------------------------------------
# YARDIMCI
# ---------------------------------------------------------

def clean(value):
    return re.sub(
        r"\s+",
        " ",
        str(value or "")
    ).strip()


def normalize(value):
    value = clean(value).casefold()

    value = unicodedata.normalize(
        "NFKD",
        value
    )

    value = "".join(
        c for c in value
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

    value = value.translate(table)

    return re.sub(
        r"[^a-z0-9]+",
        " ",
        value
    ).strip()


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
            return datetime.strptime(
                value,
                fmt
            ).strftime("%Y-%m-%d")
        except ValueError:
            pass

    m = re.search(
        r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{4})\b",
        value
    )

    if m:
        try:
            return datetime(
                int(m.group(3)),
                int(m.group(2)),
                int(m.group(1)),
            ).strftime("%Y-%m-%d")
        except ValueError:
            pass

    return ""


def get(url):
    response = requests.get(
        url,
        headers=HEADERS,
        timeout=90,
    )

    response.raise_for_status()

    return response


# ---------------------------------------------------------
# URL DÜZELTME
# ---------------------------------------------------------

def fix_url(href, current_url):
    """
    EGM'de bazı linkler yanlış şekilde:

        /www.egm.gov.tr/sehit-...

    olarak geliyor.

    Bunu:

        https://www.egm.gov.tr/sehit-...

    haline getiriyoruz.
    """

    href = clean(href)

    if not href:
        return ""

    if href.startswith(
        "javascript:"
    ):
        return ""

    if href.startswith(
        "mailto:"
    ):
        return ""

    # Zaten tam URL
    if href.startswith(
        "https://"
    ) or href.startswith(
        "http://"
    ):
        return href

    # //www.egm.gov.tr/...
    if href.startswith(
        "//www.egm.gov.tr/"
    ):
        return "https:" + href

    # /www.egm.gov.tr/...
    if href.startswith(
        "/www.egm.gov.tr/"
    ):
        return (
            "https://www.egm.gov.tr/"
            + href[
                len("/www.egm.gov.tr/") :
            ]
        )

    # /ozelharekat/...
    if href.startswith("/"):
        return urljoin(
            current_url,
            href
        )

    return urljoin(
        current_url,
        href
    )


# ---------------------------------------------------------
# ANA VERİ
# ---------------------------------------------------------

def load_base():
    print()
    print("ANA KAYNAK:")
    print(BASE_URL)

    response = get(BASE_URL)

    text = response.content.decode(
        "utf-8-sig",
        errors="replace"
    )

    reader = csv.DictReader(
        io.StringIO(text)
    )

    rows = []

    for row in reader:

        name = clean(
            row.get("ad")
        )

        if not name:
            continue

        rows.append({
            "_base": True,

            "ad_soyad": name,

            "baba_adi": clean(
                row.get("baba_adi")
            ),

            "rutbe": clean(
                row.get("rutbe")
            ),

            "kurum": clean(
                row.get("kaynak")
            ) or "sehitlerimiz.org.tr",

            "memleket": clean(
                row.get("memleket")
            ),

            "dogum_yeri": clean(
                row.get("dogum_yeri")
            ),

            "dogum_yili": clean(
                row.get("dogum_yili")
            ),

            "sehadet_tarihi": parse_date(
                row.get("sehadet_tarihi")
            ),

            "donem_cephe": clean(
                row.get("donem_cephe")
            ),

            "kaynaklar":
                "sehitlerimiz.org.tr",
        })

    print(
        "ANA KAYIT:",
        len(rows)
    )

    if len(rows) < 100000:
        raise RuntimeError(
            "ANA KAYNAK 100.000'den az kayıt döndürdü!"
        )

    return rows


# ---------------------------------------------------------
# TARİH + İSİM
# ---------------------------------------------------------

def extract_records(text, institution, source_url):

    lines = [
        clean(x)
        for x in text.splitlines()
        if clean(x)
    ]

    results = []

    numeric_date = re.compile(
        r"\b\d{1,2}[./-]\d{1,2}[./-]\d{4}\b"
    )

    for i, line in enumerate(lines):

        date_value = parse_date(line)

        if not date_value:
            continue

        candidates = []

        # Önceki birkaç satır
        for offset in range(1, 5):

            if i - offset >= 0:
                candidates.append(
                    lines[i - offset]
                )

        # Sonraki birkaç satır
        for offset in range(1, 5):

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

            if numeric_date.search(
                candidate
            ):
                continue

            if re.search(
                r"(anasayfa|iletişim|"
                r"arama|şehitlerimiz|"
                r"başkanlığı|komutanlığı|"
                r"copyright|menu|menü)",
                candidate,
                re.I,
            ):
                continue

            # URL olmasın
            if "http" in candidate.lower():
                continue

            results.append({
                "_base": False,

                "ad_soyad": candidate,

                "baba_adi": "",

                "rutbe": "",

                "kurum": institution,

                "memleket": "",

                "dogum_yeri": "",

                "dogum_yili": "",

                "sehadet_tarihi": date_value,

                "donem_cephe": "",

                "kaynaklar": source_url,
            })

            break

    return results


# ---------------------------------------------------------
# EGM
# ---------------------------------------------------------

def scrape_egm(
    url,
    institution
):

    print()
    print(
        "TARANIYOR:",
        institution
    )

    response = get(url)

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    records = []

    # Ana sayfanın metni
    records.extend(
        extract_records(
            soup.get_text("\n"),
            institution,
            url
        )
    )

    links = []

    for a in soup.find_all(
        "a",
        href=True
    ):

        text = clean(
            a.get_text(
                " ",
                strip=True
            )
        )

        href = fix_url(
            a.get("href"),
            url
        )

        if not href:
            continue

        # Sadece gerçek şehit sayfaları
        if (
            "/sehit-" not in href.lower()
            and "/sehit/" not in href.lower()
        ):
            continue

        if href not in {
            x[1] for x in links
        }:
            links.append(
                (text, href)
            )

    print(
        "Bulunan şehit sayfası:",
        len(links)
    )

    # Bireysel sayfalar
    for index, (_, link) in enumerate(
        links,
        1
    ):

        try:

            r = get(link)

            page = BeautifulSoup(
                r.text,
                "html.parser"
            )

            records.extend(
                extract_records(
                    page.get_text("\n"),
                    institution,
                    link
                )
            )

        except Exception as e:

            print(
                "UYARI:",
                link,
                str(e)
            )

    # Aynı kurum + isim + tarih
    # kendi içinde temizlenir.
    unique = {}

    for record in records:

        key = (
            normalize(
                record["ad_soyad"]
            ),
            record["sehadet_tarihi"],
            normalize(
                record["kurum"]
            ),
        )

        if key not in unique:
            unique[key] = record

    records = list(
        unique.values()
    )

    print(
        institution,
        "KAYIT:",
        len(records)
    )

    return records


# ---------------------------------------------------------
# JANDARMA
# ---------------------------------------------------------

def scrape_jandarma():

    print()
    print(
        "TARANIYOR: JANDARMA"
    )

    response = get(
        SOURCES["JANDARMA"]
    )

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    records = []

    for tr in soup.find_all("tr"):

        cells = [
            clean(
                td.get_text(
                    " ",
                    strip=True
                )
            )
            for td in tr.find_all(
                ["td", "th"]
            )
        ]

        if len(cells) < 2:
            continue

        date_value = ""

        for cell in cells:

            d = parse_date(cell)

            if d:
                date_value = d
                break

        if not date_value:
            continue

        candidates = [
            c
            for c in cells
            if c
            and not parse_date(c)
            and len(c) >= 4
        ]

        if not candidates:
            continue

        name = candidates[-1]

        records.append({
            "_base": False,

            "ad_soyad": name,

            "baba_adi": "",

            "rutbe": "",

            "kurum":
                "Jandarma Genel Komutanlığı",

            "memleket": "",

            "dogum_yeri": "",

            "dogum_yili": "",

            "sehadet_tarihi": date_value,

            "donem_cephe": "",

            "kaynaklar":
                SOURCES["JANDARMA"],
        })

    # Aynı kayıtları kendi içinde temizle.
    unique = {}

    for record in records:

        key = (
            normalize(
                record["ad_soyad"]
            ),
            record["sehadet_tarihi"],
        )

        unique[key] = record

    records = list(
        unique.values()
    )

    print(
        "JANDARMA KAYIT:",
        len(records)
    )

    # 100 tam sınırında kaldıysa
    # büyük ihtimalle pagination vardır.
    if len(records) == 100:

        raise RuntimeError(
            "Jandarma tam liste alınamadı: "
            "tam 100 kayıt geldi. "
            "Pagination tamamlanmadan veri "
            "ana kaynağa eklenmeyecek."
        )

    return records


# ---------------------------------------------------------
# SAHİL GÜVENLİK
# ---------------------------------------------------------

def scrape_sahil():

    print()
    print(
        "TARANIYOR: SAHİL GÜVENLİK"
    )

    response = get(
        SOURCES["SAHIL_GUVENLIK"]
    )

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    records = extract_records(
        soup.get_text("\n"),
        "Sahil Güvenlik Komutanlığı",
        SOURCES["SAHIL_GUVENLIK"]
    )

    unique = {}

    for record in records:

        key = (
            normalize(
                record["ad_soyad"]
            ),
            record["sehadet_tarihi"],
        )

        unique[key] = record

    records = list(
        unique.values()
    )

    print(
        "SAHİL GÜVENLİK KAYIT:",
        len(records)
    )

    return records


# ---------------------------------------------------------
# GÜÇLÜ BİRLEŞTİRME
# ---------------------------------------------------------

def merge_records(base, additions):

    """
    ÇOK ÖNEMLİ:

    BASE kayıtları ASLA birbirleriyle
    dedupe edilmez.

    Yalnızca yeni kaynaklardan gelen
    kayıtlar mevcut base ile karşılaştırılır.

    Güçlü eşleşme:

        isim + şehadet tarihi

    Tarih yoksa:

        isim + baba adı + memleket + doğum yılı

    Bunun dışında birleştirme YOK.
    """

    result = [
        dict(row)
        for row in base
    ]

    # Tarihli base kayıtlarının index'i
    dated_index = {}

    for index, row in enumerate(result):

        date_value = row[
            "sehadet_tarihi"
        ]

        if not date_value:
            continue

        key = (
            normalize(
                row["ad_soyad"]
            ),
            date_value,
        )

        dated_index.setdefault(
            key,
            []
        ).append(index)

    added = 0
    merged = 0

    for new in additions:

        name = normalize(
            new["ad_soyad"]
        )

        date_value = new[
            "sehadet_tarihi"
        ]

        matched_index = None

        # ---------------------------------------------
        # 1. En güçlü eşleşme:
        # isim + tarih
        # ---------------------------------------------

        if name and date_value:

            key = (
                name,
                date_value,
            )

            candidates = dated_index.get(
                key,
                []
            )

            if len(candidates) == 1:
                matched_index = candidates[0]

        # ---------------------------------------------
        # Eşleştiyse bilgileri zenginleştir
        # ---------------------------------------------

        if matched_index is not None:

            old = result[
                matched_index
            ]

            for field in [
                "baba_adi",
                "rutbe",
                "kurum",
                "memleket",
                "dogum_yeri",
                "dogum_yili",
                "donem_cephe",
            ]:

                if (
                    not old.get(field)
                    and new.get(field)
                ):
                    old[field] = new[field]

            old_sources = set(
                filter(
                    None,
                    old["kaynaklar"]
                    .split(";")
                )
            )

            new_sources = set(
                filter(
                    None,
                    new["kaynaklar"]
                    .split(";")
                )
            )

            old[
                "kaynaklar"
            ] = ";".join(
                sorted(
                    old_sources
                    | new_sources
                )
            )

            merged += 1

        else:

            # -----------------------------------------
            # GERÇEKTEN YENİ KAYIT
            # -----------------------------------------

            result.append(
                dict(new)
            )

            new_index = len(
                result
            ) - 1

            if date_value:

                key = (
                    name,
                    date_value,
                )

                dated_index.setdefault(
                    key,
                    []
                ).append(
                    new_index
                )

            added += 1

    return result, merged, added


# ---------------------------------------------------------
# CSV
# ---------------------------------------------------------

def write_csv(
    rows,
    filename
):

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

            identity = "|".join([
                normalize(
                    row["ad_soyad"]
                ),
                row["sehadet_tarihi"],
                normalize(
                    row["baba_adi"]
                ),
                normalize(
                    row["memleket"]
                ),
                normalize(
                    row["kurum"]
                ),
            ])

            row_id = hashlib.sha256(
                identity.encode(
                    "utf-8"
                )
            ).hexdigest()[:20]

            output = {
                "id": row_id,
                "ad_soyad":
                    row["ad_soyad"],
                "baba_adi":
                    row["baba_adi"],
                "rutbe":
                    row["rutbe"],
                "kurum":
                    row["kurum"],
                "memleket":
                    row["memleket"],
                "dogum_yeri":
                    row["dogum_yeri"],
                "dogum_yili":
                    row["dogum_yili"],
                "sehadet_tarihi":
                    row["sehadet_tarihi"],
                "donem_cephe":
                    row["donem_cephe"],
                "kaynaklar":
                    row["kaynaklar"],
            }

            writer.writerow(
                output
            )

    return path


# ---------------------------------------------------------
# MAIN
# ---------------------------------------------------------

def main():

    base = load_base()

    additions = []

    # EGM
    additions.extend(
        scrape_egm(
            SOURCES["EGM"],
            "Emniyet Genel Müdürlüğü"
        )
    )

    # EGM Özel Harekât
    additions.extend(
        scrape_egm(
            SOURCES[
                "EGM_OZEL_HAREKAT"
            ],
            "EGM Özel Harekât"
        )
    )

    # EGM Havacılık
    additions.extend(
        scrape_egm(
            SOURCES[
                "EGM_HAVACILIK"
            ],
            "EGM Havacılık"
        )
    )

    # Jandarma
    additions.extend(
        scrape_jandarma()
    )

    # Sahil Güvenlik
    additions.extend(
        scrape_sahil()
    )

    print()
    print(
        "======================================"
    )
    print(
        "BİRLEŞTİRME BAŞLIYOR"
    )
    print(
        "======================================"
    )

    merged, matched, added = merge_records(
        base,
        additions
    )

    # Tarihe göre sırala ama
    # kayıt sayısını değiştirme.
    merged.sort(
        key=lambda x: (
            x["sehadet_tarihi"] == "",
            x["sehadet_tarihi"],
            normalize(
                x["ad_soyad"]
            )
        )
    )

    dated = [
        row
        for row in merged
        if row["sehadet_tarihi"]
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
    print(
        "======================================"
    )
    print(
        "SONUÇ"
    )
    print(
        "======================================"
    )

    print(
        "Ana kayıt:",
        len(base)
    )

    print(
        "Ek kaynak ham kayıt:",
        len(additions)
    )

    print(
        "Mevcut kayıtlarla eşleşen:",
        matched
    )

    print(
        "Gerçekten yeni eklenen:",
        added
    )

    print(
        "TOPLAM BİRLEŞİK:",
        len(merged)
    )

    print(
        "Tam tarihli:",
        len(dated)
    )

    print(
        "Tüm veri:",
        all_path
    )

    print(
        "Takvim:",
        calendar_path
    )

    print(
        "======================================"
    )

    # Ana veri kesinlikle küçülmemeli.
    if len(merged) < len(base):

        raise RuntimeError(
            "KRİTİK HATA: Birleşik veri "
            "ana veriden daha az!"
        )


if __name__ == "__main__":
    main()
