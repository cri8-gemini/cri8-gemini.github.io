"""수집한 CSV 두 개를 ISO 주차로 병합해 index.html 과 merged CSV 를 만든다.

usage:
    python scripts/build_site.py
"""

import csv
import datetime as dt
import json
import os

USMEF_CSV = "data/usmef_weekly.csv"
STOCK_CSV = "data/txrh_weekly.csv"
MERGED_CSV = "data/merged_weekly.csv"
OUT_HTML = "index.html"

# 차트에 노출할 육류 지표. key 는 CSV 컬럼명.
MEAT_SERIES = [
    {"key": "beef", "label": "소고기 종합"},
    {"key": "beef_116", "label": "소고기 116A"},
    {"key": "pork", "label": "돼지고기 종합"},
    {"key": "pork_123a", "label": "돼지고기 123A"},
]

STOCK_LABEL = "TXRH"


def iso_week(date_str):
    """'2005-01-04' -> '2005-W01'. 두 소스를 맞추는 기준 키."""
    year, week, _ = dt.date.fromisoformat(date_str).isocalendar()
    return f"{year}-W{week:02d}"


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as fp:
        return list(csv.DictReader(fp))


def to_float(value):
    """가격을 float 으로. 결측은 None.

    원본 API 는 결측 주를 빈 문자열이 아니라 "0.00" 으로 내려보내는 경우가 있다
    (예: 2017-10-07 의 priceBeef — 같은 행의 나머지 항목은 정상값). 시세가 0 일
    수는 없으므로 0 이하는 결측으로 본다. 그대로 두면 지수 기준값·상관계수·축
    범위가 전부 오염된다.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def merge():
    """ISO 주차를 키로 육류 시세와 주가를 합친다.

    날짜는 육류 쪽 실제 고시일을 쓰되, 그 주에 육류 데이터가 없으면 주가 쪽
    날짜를 쓴다. 어느 한쪽만 있는 주도 버리지 않고 남긴다 (해당 값은 None).
    """
    weeks = {}

    for row in read_csv(USMEF_CSV):
        key = iso_week(row["date"])
        entry = weeks.setdefault(key, {"date": None, "stock_date": None})
        entry["date"] = row["date"]
        for series in MEAT_SERIES:
            entry[series["key"]] = to_float(row.get(series["key"]))

    for row in read_csv(STOCK_CSV):
        key = iso_week(row["date"])
        entry = weeks.setdefault(key, {"date": None, "stock_date": None})
        entry["stock_date"] = row["date"]
        entry["txrh"] = to_float(row.get("adj_close"))
        entry["txrh_close"] = to_float(row.get("close"))

    merged = []
    for key in sorted(weeks):
        entry = weeks[key]
        entry["week"] = key
        entry["date"] = entry["date"] or entry["stock_date"]
        merged.append(entry)
    return merged


def write_merged_csv(rows):
    columns = ["week", "date", "txrh", *[s["key"] for s in MEAT_SERIES]]
    with open(MERGED_CSV, "w", newline="", encoding="utf-8") as fp:
        writer = csv.writer(fp, lineterminator="\n")  # LF 고정 — collect_usmef.py 참고
        writer.writerow(columns)
        for row in rows:
            writer.writerow([row.get(c) if row.get(c) is not None else "" for c in columns])


def build_payload(rows):
    keys = ["txrh", *[s["key"] for s in MEAT_SERIES]]
    return {
        "generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "stockLabel": STOCK_LABEL,
        "meat": MEAT_SERIES,
        "columns": keys,
        # [날짜, txrh, beef, beef_116, pork, pork_123a]
        "rows": [[r["date"], *[r.get(k) for k in keys]] for r in rows if r.get("date")],
    }


def main():
    rows = merge()
    write_merged_csv(rows)

    payload = build_payload(rows)
    template_path = os.path.join(os.path.dirname(__file__), "template.html")
    with open(template_path, encoding="utf-8") as fp:
        template = fp.read()

    # </script> 가 데이터 안에 들어갈 일은 없지만 방어적으로 이스케이프한다.
    data_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    data_json = data_json.replace("</", "<\\/")

    html = template.replace("/*__DATA__*/null", data_json)
    with open(OUT_HTML, "w", encoding="utf-8", newline="\n") as fp:  # LF 고정
        fp.write(html)

    covered = [r for r in payload["rows"] if r[1] is not None and r[2] is not None]
    print(f"{len(payload['rows'])}주 -> {OUT_HTML} ({MERGED_CSV})")
    print(f"기간: {payload['rows'][0][0]} ~ {payload['rows'][-1][0]}")
    print(f"주가·육류 모두 있는 주: {len(covered)}")


if __name__ == "__main__":
    main()
