"""USMEF NEWSLINE 주간 PDF 에서 가격표를 뽑아 CSV 로 만든다.

PDF 는 usmef.co.kr 에 주 1회(대개 수요일) 올라오고, 한 호에 최근 5주치 표가
들어 있다. 그래서 호가 하나 빠져도 이웃 호가 그 주를 덮어 준다.

주의할 점 둘:
- 없는 날짜를 요청해도 서버가 404 를 주지 않는다. HTTP 200 에 3KB 짜리 안내
  PDF 를 돌려주므로 크기로 걸러야 한다.
- 일부 호는 글자가 벡터로 변환돼 있어 텍스트 추출이 안 된다(이미지 PDF).
  그 호는 건너뛰고, 겹치는 주는 이웃 호에서 회수한다.

usage:
    python scripts/parse_newsline.py --year 2026
"""

import argparse
import csv
import datetime as dt
import os
import re
import sys
import time
import urllib.request
from collections import defaultdict

import pymupdf

import newsline_stats

PDF_URL = "https://usmef.co.kr/ebook/newsline/{year}/{key}/{key}.pdf"
CACHE = "data/newsline_pdf"
OUT = "data/newsline_cuts.csv"
OUT_STATS = "data/newsline_stats.csv"

# 안내 PDF 가 3KB 안팎이라 넉넉히 잡는다.
MIN_PDF_BYTES = 50_000

DATE_TOKEN = re.compile(r"^\d{1,2}/\d{1,2}$")
NUMBER = re.compile(r"^-?[\d,]+\.?\d*$")

# 열 중심에서 이 거리 안쪽의 숫자만 그 열의 값으로 본다.
# "6월 평균" 열은 날짜 토큰이 아니라 열로 잡히지 않는데, 이 거리 제한이 없으면
# 평균값이 옆 날짜 열로 흘러들어간다.
COL_TOLERANCE = 45
ROW_TOLERANCE = 14
TIGHT_ROW_TOLERANCE = 7   # 행을 좁게 끊을 때
ORPHAN_GAP = 22           # 라벨만 있는 행을 값 행에 붙일 최대 거리

# 표별 최대 높이(pt). 소고기 17행 / 돼지 11행 / 지육 2행.
# 지육 표를 넓게 잡으면 아래 차트 눈금과 푸터 문구까지 행으로 잡힌다.
MAX_TABLE_HEIGHT = {"beef_cut": 700, "pork_cut": 500, "carcass": 160}
LETTER = re.compile(r"[A-Za-z가-힣]")
DECIMAL = re.compile(r"^\d+\.\d+$")


def fetch(year, key, path):
    """PDF 를 받아 캐시에 저장. 실제 발행분이 아니면 False."""
    if os.path.exists(path):
        return os.path.getsize(path) > MIN_PDF_BYTES

    req = urllib.request.Request(PDF_URL.format(year=year, key=key),
                                 headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read()
    except Exception:
        return False

    if len(body) < MIN_PDF_BYTES:
        return False
    with open(path, "wb") as fp:
        fp.write(body)
    return True


def group_rows(words, tol=ROW_TOLERANCE):
    """단어를 y 좌표로 묶어 행으로 만든다.

    반올림으로 묶으면 안 된다. 같은 행이라도 라벨과 숫자의 y 가 몇 pt 어긋나는데
    (예: '120 Brisket' 라벨 8502 / 값 8496), 하필 경계에 걸리면 한 행이 둘로
    쪼개져 라벨 없는 행과 값 없는 행이 되고 둘 다 버려진다. 행 간격은 30pt 쯤
    되므로 간격이 tol 보다 벌어질 때만 새 행으로 끊는다.
    """
    rows = {}
    current, last = None, None
    for word in sorted(words, key=lambda w: w[1]):
        if last is None or word[1] - last > tol:
            current = word[1]
            rows[current] = []
        rows[current].append(word)
        last = word[1]
    return rows


def find_tables(words):
    """날짜 열이 4~6개인 헤더 행만 고른다.

    차트 축 라벨도 날짜처럼 생겼지만(1/8 … 12/8, 또는 주간 5개짜리 두 벌)
    열 개수가 10~12개라 이 조건에서 걸러진다.
    """
    tables = []
    for y, row in group_rows(words).items():
        dates = [w for w in row if DATE_TOKEN.match(w[4])]
        if not 4 <= len(dates) <= 6:
            continue
        cols = sorted(((w[4], (w[0] + w[2]) / 2) for w in dates), key=lambda c: c[1])
        has_bpn = any(w[4].startswith("BPN") for w in row)
        tables.append({"y": y, "cols": cols, "pork_cuts": has_bpn})
    return sorted(tables, key=lambda t: t["y"])


def resolve_date(token, issue_date):
    """'12/6' + 발행일 -> 실제 날짜. 연말 호는 전년도 열을 함께 싣는다."""
    month, day = (int(x) for x in token.split("/"))
    try:
        date = dt.date(issue_date.year, month, day)
    except ValueError:
        return None
    if date > issue_date:
        date = dt.date(issue_date.year - 1, month, day)
    return date


def parse_table(words, table, next_y, kind):
    """표 하나에서 (라벨, {날짜: 값}) 목록을 뽑는다."""
    left = min(c[1] for c in table["cols"]) - COL_TOLERANCE
    # 표 아래로 차트가 이어진다. 다음 표까지 통째로 훑으면 차트 축 눈금(6, 8, 810…)과
    # 푸터 문구까지 행으로 잡힌다. 표 하나가 차지하는 최대 높이로 끊는다.
    end = min(next_y, table["y"] + MAX_TABLE_HEIGHT[kind])
    body = [w for w in words if table["y"] + ROW_TOLERANCE < w[1] < end]

    # 좁게 묶는다. 넓히면 부위 표의 이웃 행들이 한 덩어리로 뭉친다.
    entries = []
    grouped = group_rows(body, tol=TIGHT_ROW_TOLERANCE)
    for y in sorted(grouped):
        row = sorted(grouped[y], key=lambda w: w[0])
        entries.append({
            "y": y,
            "label": " ".join(w[4] for w in row if w[2] < left).strip(),
            "cells": [w for w in row if w[0] >= left and NUMBER.match(w[4])],
        })

    # 라벨과 값의 세로 위치가 표마다 다르다. 부위 표는 라벨이 값보다 6pt 위,
    # 지육 표는 14pt 아래에 있다. 임계값 하나로 둘을 다 맞출 수 없어서, 일단
    # 좁게 끊은 뒤 '값만 있는 행'과 '라벨만 있는 행'을 이웃끼리 짝지어 붙인다.
    for i, entry in enumerate(entries):
        if entry["label"] or not entry["cells"]:
            continue
        for j in (i - 1, i + 1):
            if 0 <= j < len(entries) and abs(entries[j]["y"] - entry["y"]) <= ORPHAN_GAP \
                    and entries[j]["label"] and not entries[j]["cells"]:
                entry["label"] = entries[j]["label"]
                entries[j]["label"] = ""
                break

    out = []
    for entry in entries:
        label, row = entry["label"], entry["cells"]
        # 차트 눈금은 숫자뿐이다. 품목명에는 반드시 글자가 있다.
        if not LETTER.search(label):
            continue
        # 월평균 열은 주간 열 왼쪽에도 붙는다(예: 2월호의 '1월 평균'). 날짜가 없어
        # 열로 잡히지 않는데, 그 값이 라벨 오른쪽 끝에 딸려 들어온다. 품목 코드는
        # 112A·160 처럼 소수점이 없으므로 끝에 붙은 소수만 떼어낸다.
        parts = label.split()
        while parts and DECIMAL.match(parts[-1]):
            parts.pop()
        label = " ".join(parts)
        if not label:
            continue
        values = {}
        for word in row:
            if word[0] < left or not NUMBER.match(word[4]):
                continue
            centre = (word[0] + word[2]) / 2
            token, dist = None, COL_TOLERANCE
            for name, cx in table["cols"]:
                if abs(cx - centre) < dist:
                    token, dist = name, abs(cx - centre)
            if token:
                values[token] = float(word[4].replace(",", ""))
        if label and values:
            out.append((label, values))
    return out


def parse_pdf(path, issue_date):
    page = pymupdf.open(path)[0]
    words = page.get_text("words")
    if len(words) < 200:
        return [], []  # 글자가 벡터로 변환된 호 — 이웃 호에서 회수한다

    tables = find_tables(words)
    if len(tables) < 3:
        return [], []

    # 문서 순서대로 소고기 부위 / 돼지 부위 / 지육.
    # 돼지 표는 헤더에 BPN 이 있어 교차 확인이 된다.
    kinds = ["beef_cut", "pork_cut", "carcass"]
    if not tables[1]["pork_cuts"]:
        print(f"  ! {path}: 돼지 표 위치가 예상과 다름", file=sys.stderr)

    records = []
    for kind, table, nxt in zip(kinds, tables[:3], [t["y"] for t in tables[1:4]] + [1e9]):
        for label, values in parse_table(words, table, nxt, kind):
            for token, value in values.items():
                date = resolve_date(token, issue_date)
                if date:
                    records.append({
                        "week": date.isoformat(), "kind": kind,
                        "item": label, "value": value,
                    })

    # 시장동향 카드는 "지난주" 기준이다. 그 호 가격표의 가장 최근 주에 맞춘다.
    # 수출량만은 집계가 더 늦어 본문이 밝힌 자체 날짜를 쓴다.
    stats = []
    latest = max((r["week"] for r in records), default=None)
    for stat in newsline_stats.extract(page, issue_date):
        week = stat.pop("week", None) or latest
        if week:
            stats.append({"week": week, **stat})
    return records, stats


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=dt.date.today().year)
    parser.add_argument("-o", "--out", default=OUT)
    args = parser.parse_args()

    os.makedirs(CACHE, exist_ok=True)
    start, end = dt.date(args.year, 1, 1), min(dt.date(args.year, 12, 31), dt.date.today())

    issues, records, stats = [], [], []
    date = start
    while date <= end:
        key = date.strftime("%Y%m%d")
        path = os.path.join(CACHE, key + ".pdf")
        if fetch(args.year, key, path):
            issues.append(key)
            got, got_stats = parse_pdf(path, date)
            print(f"{key}: 가격 {len(got)}건 / 지표 {len(got_stats)}건"
                  + ("" if got else "  (텍스트 없음 — 건너뜀)"))
            records.extend(got)
            stats.extend(got_stats)
            time.sleep(0.2)
        date += dt.timedelta(1)

    # 같은 주가 여러 호에 실린다. 값이 갈리면 나중 호를 믿는다(정정 반영).
    merged = {}
    for r in records:
        merged[(r["week"], r["kind"], r["item"])] = r

    rows = sorted(merged.values(), key=lambda r: (r["week"], r["kind"], r["item"]))
    with open(args.out, "w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=["week", "kind", "item", "value"],
                                lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    merged_stats = {}
    for r in stats:
        merged_stats[(r["week"], r["species"], r["metric"])] = r
    stat_rows = sorted(merged_stats.values(),
                       key=lambda r: (r["week"], r["species"], r["metric"]))
    with open(OUT_STATS, "w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=["week", "species", "metric", "value", "prev"],
                                lineterminator="\n")
        writer.writeheader()
        writer.writerows(stat_rows)

    weeks = sorted({r["week"] for r in rows})
    print(f"\n발행분 {len(issues)}호 -> 가격 {len(rows)}건 / {len(weeks)}주 -> {args.out}")
    print(f"                지표 {len(stat_rows)}건 -> {OUT_STATS}")
    if weeks:
        print(f"기간: {weeks[0]} ~ {weeks[-1]}")


if __name__ == "__main__":
    main()
