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
CUTS_CSV = "data/newsline_cuts.csv"
OUT_HTML = "index.html"

# 차트에서 TXRH 와 겹쳐 볼 지표. key 는 병합 CSV 의 컬럼명, group 은 버튼 줄.
#
# 라벨과 단위는 USMEF NEWSLINE PDF 로 확인했다(주간 137주 전량 소수점까지 일치).
# 주의: price123a 는 필드 순서상 pricePig 옆에 있지만 실제로는 **소고기** 부위다.
# PDF 의 소고기 부위 표에 123A Short Rib 로 실려 있다.
MEAT_SERIES = [
    {"key": "beef", "label": "소 지육", "group": "가격", "unit": "$/100kg"},
    {"key": "beef_116", "label": "소 116A", "group": "가격", "unit": "$/kg"},
    {"key": "pork_123a", "label": "소 123A", "group": "가격", "unit": "$/kg"},
    {"key": "pork", "label": "돼지 지육", "group": "가격", "unit": "$/100kg"},
    {"key": "beef_cutout", "label": "소 컷아웃", "group": "가격", "unit": "$/lb"},
    {"key": "pork_cutout", "label": "돼지 컷아웃", "group": "가격", "unit": "$/lb"},
    {"key": "beef_live_price", "label": "생우", "group": "가격", "unit": "$/100lb"},
    {"key": "pork_live_price", "label": "생돈", "group": "가격", "unit": "$/100lb"},
    {"key": "cut_112a", "label": "립아이", "group": "부위", "unit": "$/kg"},
    {"key": "cut_180", "label": "스트립로인", "group": "부위", "unit": "$/kg"},
    {"key": "cut_184", "label": "탑버트(설로인)", "group": "부위", "unit": "$/kg"},
    {"key": "cut_189a", "label": "텐더로인(필레)", "group": "부위", "unit": "$/kg"},
    {"key": "cut_120", "label": "브리스킷", "group": "부위", "unit": "$/kg"},
    {"key": "cut_193", "label": "플랭크", "group": "부위", "unit": "$/kg"},
    {"key": "beef_slaughter", "label": "소 도축두수", "group": "수급", "unit": "두"},
    {"key": "pork_slaughter", "label": "돼지 도축두수", "group": "수급", "unit": "두"},
    {"key": "beef_production", "label": "소 생산량", "group": "수급", "unit": "lb"},
    {"key": "pork_production", "label": "돼지 생산량", "group": "수급", "unit": "lb"},
    {"key": "beef_export_korea", "label": "소 한국수출", "group": "수급", "unit": "톤"},
    {"key": "pork_export_korea", "label": "돼지 한국수출", "group": "수급", "unit": "톤"},
]

# newsline_stats.csv 에서 위 컬럼으로 끌어올 지표
STAT_KEYS = ["cutout", "live_price", "slaughter", "production", "export_korea"]

# newsline_cuts.csv 의 품목명 -> 위 컬럼. TXRH 메뉴에 실제로 오르는 부위들이다.
# 116A·123A 는 JSON API 에도 있어 이미 '가격' 줄에 들어가 있으므로 뺀다.
CUT_ITEMS = {
    "112A Ribeye Roll, boneless, light": "cut_112a",
    "180 Strip Loin, boneless. 1x1": "cut_180",
    "184 Loin, top butt, boneless": "cut_184",
    "189A Tenderloin trimmed heavy": "cut_189a",
    "120 Brisket, boneless": "cut_120",
    "193 Flank Steak": "cut_193",
}

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

    for key, values in cuts_by_week().items():
        weeks.setdefault(key, {"date": None, "stock_date": None}).update(values)

    for key, values in stats_by_week().items():
        weeks.setdefault(key, {"date": None, "stock_date": None}).update(values)

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


# 원본 PDF 에 자릿수가 빠진 오타가 있다. 예: 2022-12-24 립아이가 2.45 로 찍혀
# 있는데 같은 행의 앞뒤 주는 24.47 / 27.32 다. 같은 주를 싣는 네 개 호가 모두
# 같은 오타라 이웃 호로도 회수되지 않는다.
#
# 진짜 급등락을 지우지 않도록 조건을 좁힌다 — 한 점만 2배 이상 튀고, 그 앞뒤가
# 서로 15% 안쪽으로 붙어 있을 때만 버린다. 코로나 폭락처럼 여러 주에 걸친
# 움직임이나 50% 수준의 변동은 걸리지 않는다.
OUTLIER_RATIO = 2.0
NEIGHBOUR_GAP = 0.15


def drop_digit_typos(series, label):
    """{주차: 값} 에서 자릿수 오타로 보이는 점을 뺀다."""
    weeks = sorted(series)
    for i in range(1, len(weeks) - 1):
        prev, current, nxt = (series[weeks[j]] for j in (i - 1, i, i + 1))
        if not (prev and current and nxt):
            continue
        ratios = (current / prev, current / nxt)
        spiked = all(r >= OUTLIER_RATIO or r <= 1 / OUTLIER_RATIO for r in ratios)
        if spiked and abs(prev / nxt - 1) < NEIGHBOUR_GAP:
            print(f"  ! 원본 오타로 보여 제외: {label} {weeks[i]} "
                  f"{current:g} (앞 {prev:g} / 뒤 {nxt:g})")
            series[weeks[i]] = None
    return series


def cuts_by_week():
    """newsline_cuts.csv 에서 부위별 가격을 {ISO주차: {컬럼: 값}} 으로."""
    by_item = {}
    for row in read_csv(CUTS_CSV):
        column = CUT_ITEMS.get(row["item"])
        if column:
            by_item.setdefault(column, {})[iso_week(row["week"])] = to_float(row["value"])

    out = {}
    for column, series in by_item.items():
        for week, value in drop_digit_typos(series, column).items():
            if value is not None:
                out.setdefault(week, {})[column] = value
    return out


def stats_by_week():
    """newsline_stats.csv 를 {ISO주차: {컬럼: 값}} 으로 만든다.

    가격표·주가와 같은 ISO 주차 키로 맞춰야 한 행에 나란히 놓인다.
    """
    out = {}
    for row in read_csv(STATS_CSV):
        if row["metric"] not in STAT_KEYS:
            continue
        column = f"{row['species']}_{row['metric']}"
        out.setdefault(iso_week(row["week"]), {})[column] = to_float(row["value"])
    return out


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
