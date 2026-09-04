#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import csv
import io
import hashlib
import re
from datetime import datetime
from pathlib import Path

import requests


# ============================================================
# AYARLAR
# ============================================================

SOURCE_URL = "https://sehitlerimiz.org.tr/veri/sehitler.csv"

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

RAW_FILE = DATA_DIR / "sehitler.csv"
COMBINED_FILE = DATA_DIR / "sehitlerimiz_birlesik.csv"
CALENDAR_FILE = DATA_DIR / "sehitlerimiz_takvim.csv"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/140.0 Safari/537.36"
    ),
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
}


# ============================================================
# TEMİZLEME
# ============================================================

def clean(value):
    return re.sub(
        r"\s+",
        " ",
        str(value or "")
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
    ]

    for fmt in formats:
        try:
            return datetime.strptime(
                value,
                fmt
            ).strftime("%Y-%m-%d")
        except ValueError:
            pass

    return ""


# ============================================================
# CSV'Yİ ÇEK
# ============================================================

def download_source():

    print()
    print("=" * 60)
    print("SEHITLERIMIZ.ORG.TR VERISI CEKILIYOR")
    print("=" * 60)
    print(SOURCE_URL)
    print()

    response = requests.get(
        SOURCE_URL,
        headers=HEADERS,
        timeout=120
    )

    response.raise_for_status()

    if len(response.content) < 1_000_000:
        raise RuntimeError(
            "CSV beklenenden küçük geldi. "
            "Kaynak düzgün indirilememiş olabilir."
        )

    RAW_FILE.write_bytes(
        response.content
    )

    print(
        "Indirilen boyut:",
        f"{len(response.content):,}",
        "byte"
    )

    return response.content


# ============================================================
# CSV'Yİ OKU
# ============================================================

def read_source(data):

    text = data.decode(
        "utf-8-sig",
        errors="replace"
    )

    reader = csv.DictReader(
        io.StringIO(text)
    )

    expected = {
        "ad",
        "baba_adi",
        "rutbe",
        "memleket",
        "dogum_yeri",
        "dogum_yili",
        "sehadet_tarihi",
        "donem_cephe",
        "kaynak",
        "sayfa",
    }

    missing = expected - set(
        reader.fieldnames or []
    )

    if missing:
        raise RuntimeError(
            "CSV sütunları beklenenden farklı! "
            f"Eksik: {missing}"
        )

    rows = []

    for row in reader:

        name = clean(
            row.get("ad")
        )

        # İsimsiz / boş kayıtları alma.
        if not name:
            continue

        rows.append({
            "ad_soyad": name,

            "baba_adi": clean(
                row.get("baba_adi")
            ),

            "rutbe": clean(
                row.get("rutbe")
            ),

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

            "kaynak": clean(
                row.get("kaynak")
            ),

            "sayfa": clean(
                row.get("sayfa")
            ),
        })

    return rows


# ============================================================
# ID ÜRET
# ============================================================

def make_id(row):

    raw = "|".join([
        row["ad_soyad"],
        row["baba_adi"],
        row["rutbe"],
        row["memleket"],
        row["dogum_yeri"],
        row["dogum_yili"],
        row["sehadet_tarihi"],
        row["donem_cephe"],
        row["kaynak"],
        row["sayfa"],
    ])

    return hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()[:24]


# ============================================================
# BİRLEŞİK CSV
# ============================================================

def write_combined(rows):

    fields = [
        "id",
        "ad_soyad",
        "baba_adi",
        "rutbe",
        "memleket",
        "dogum_yeri",
        "dogum_yili",
        "sehadet_tarihi",
        "donem_cephe",
        "kaynak",
        "sayfa",
    ]

    with COMBINED_FILE.open(
        "w",
        encoding="utf-8-sig",
        newline=""
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=fields
        )

        writer.writeheader()

        for row in rows:

            output = dict(row)

            output["id"] = make_id(
                row
            )

            writer.writerow(
                output
            )

    print(
        "Birlesik CSV:",
        COMBINED_FILE
    )


# ============================================================
# TAKVİM VERİSİ
# ============================================================

def write_calendar_csv(rows):

    fields = [
        "id",
        "ad_soyad",
        "baba_adi",
        "rutbe",
        "memleket",
        "dogum_yeri",
        "dogum_yili",
        "sehadet_tarihi",
        "donem_cephe",
        "kaynak",
        "sayfa",
    ]

    dated = [
        row
        for row in rows
        if row["sehadet_tarihi"]
    ]

    dated.sort(
        key=lambda row: (
            row["sehadet_tarihi"],
            row["ad_soyad"]
        )
    )

    with CALENDAR_FILE.open(
        "w",
        encoding="utf-8-sig",
        newline=""
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=fields
        )

        writer.writeheader()

        for row in dated:

            output = dict(row)

            output["id"] = make_id(
                row
            )

            writer.writerow(
                output
            )

    print(
        "Tam tarihli kayıt:",
        len(dated)
    )

    print(
        "Takvim CSV:",
        CALENDAR_FILE
    )

    return dated


# ============================================================
# ANA
# ============================================================

def main():

    data = download_source()

    rows = read_source(
        data
    )

    print()
    print("=" * 60)
    print("SONUC")
    print("=" * 60)

    print(
        "Toplam kayıt:",
        f"{len(rows):,}"
    )

    if len(rows) < 100000:

        raise RuntimeError(
            "KRITIK HATA: 100.000'den az kayıt geldi!"
        )

    write_combined(
        rows
    )

    dated = write_calendar_csv(
        rows
    )

    print()
    print("=" * 60)
    print("TAMAMLANDI")
    print("=" * 60)

    print(
        "Ana kayıt:",
        f"{len(rows):,}"
    )

    print(
        "Tam tarihli:",
        f"{len(dated):,}"
    )

    print(
        "Eksik tarihli:",
        f"{len(rows) - len(dated):,}"
    )

    print()
    print(
        "Ana veri:",
        COMBINED_FILE
    )

    print(
        "Takvim verisi:",
        CALENDAR_FILE
    )


if __name__ == "__main__":
    main()
