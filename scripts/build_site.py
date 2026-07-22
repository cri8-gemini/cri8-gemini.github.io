"""수집한 CSV 두 개를 ISO 주차로 병합해 index.html 과 merged CSV 를 만든다.

usage:
    python scripts/build_site.py
"""

import csv
import datetime as dt
import json
import os

USMEF_CSV = "data/usmef_weekly.csv"
STOCK_CSV = "data/stocks/TXRH.csv"
MERGED_CSV = "data/merged_weekly.csv"
STATS_CSV = "data/newsline_stats.csv"
OUT_HTML = "index.html"

# 차트에 노출할 육류 지표. key 는 CSV 컬럼명.
# 라벨과 단위는 USMEF NEWSLINE PDF 로 확인했다(주간 32주 전량 소수점까지 일치).
# 주의: price123a 는 필드 순서상 pricePig 옆에 있지만 실제로는 **소고기** 부위다.
# PDF 의 소고기 부위 표에 123A Short Rib 로 실려 있다.
MEAT_SERIES = [
    {"key": "beef", "label": "소고기 지육 ($/100kg)"},
    {"key": "beef_116", "label": "소고기 116A Chuck Roll ($/kg)"},
    {"key": "pork", "label": "돼지 지육 ($/100kg)"},
    {"key": "pork_123a", "label": "소고기 123A Short Rib ($/kg)"},
]

STOCK_LABEL = "TXRH"

# 시장동향 지표. 단위가 제각각이라 한 축에 못 올리고 지표마다 차트를 따로 둔다.
# scale/suffix 는 화면 표기용 (525000 -> "52.5만 두").
STAT_METRICS = [
    {"key": "cutout", "label": "컷아웃 가격", "unit": "$/lb",
     "prefix": "$", "scale": 1, "suffix": "", "digits": 2},
    {"key": "live_price", "label": "생축 현금가", "unit": "$/100lb",
     "prefix": "$", "scale": 1, "suffix": "", "digits": 2},
    {"key": "slaughter", "label": "도축두수", "unit": "두",
     "prefix": "", "scale": 10000, "suffix": "만 두", "digits": 1},
    {"key": "production", "label": "생산량", "unit": "파운드",
     "prefix": "", "scale": 100000000, "suffix": "억 lb", "digits": 2},
    {"key": "export_korea", "label": "한국향 수출량", "unit": "톤",
     "prefix": "", "scale": 1000, "suffix": "천 톤", "digits": 2},
]
SPECIES = [{"key": "beef", "label": "소고기"}, {"key": "pork", "label": "돼지고기"}]


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


def read_stats():
    """축종별 주간 지표를 {축종: [[주차, 지표...], ...]} 로 만든다.

    주가 비어 있는 구간은 값을 채우지 않고 None 으로 남긴다. 2025년 10~11월
    생산량처럼 실제로 발표되지 않은 구간이 있는데, 이어 그리면 없던 데이터를
    있는 것처럼 보이게 된다.
    """
    keys = [m["key"] for m in STAT_METRICS]
    table = {s["key"]: {} for s in SPECIES}
    for row in read_csv(STATS_CSV):
        if row["species"] not in table or row["metric"] not in keys:
            continue
        table[row["species"]].setdefault(row["week"], {})[row["metric"]] = to_float(row["value"])

    out = {}
    for species, weeks in table.items():
        out[species] = [[week, *[weeks[week].get(k) for k in keys]]
                        for week in sorted(weeks)]
    return out


def build_payload(rows):
    keys = ["txrh", *[s["key"] for s in MEAT_SERIES]]
    return {
        "generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "stockLabel": STOCK_LABEL,
        "meat": MEAT_SERIES,
        "columns": keys,
        "statMetrics": STAT_METRICS,
        "species": SPECIES,
        "stats": read_stats(),
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
