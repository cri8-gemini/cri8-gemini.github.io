"""NEWSLINE 파싱 결과를 검증한다.

PDF 레이아웃이 해마다 바뀌므로 과거 연도를 새로 파싱했으면 반드시 돌린다.
파서가 조용히 틀리는 걸 잡아내는 게 목적이라, 세 가지를 서로 다른 근거로 본다.

1. JSON API 대조 — 지육 2종과 116A·123A 는 양쪽에 다 있다. 값이 어긋나면
   파싱이 틀린 것이다. 가장 강한 근거.
2. 전주값 체인 — 각 호의 '전 주' 값은 직전 호의 본값과 같아야 한다. API 에
   없는 지표(도축두수·생산량 등)를 이 방법으로 본다. 생산량·도축두수는 USDA
   가 사후 조정하므로 어긋나는 게 정상이고, 그 사실은 PDF 에 각주로 적혀 있다.
3. 값 범위 — 자릿수가 튀는 값을 찾는다. 증감폭이나 단위 라벨이 값 자리로
   흘러들면 여기서 드러난다.

usage:
    python scripts/verify_newsline.py
"""

import csv
import datetime as dt
import sys
from collections import defaultdict

CUTS = "data/newsline_cuts.csv"
STATS = "data/newsline_stats.csv"
API = "data/merged_weekly.csv"

# PDF 품목 -> JSON API 컬럼. 양쪽에 다 있는 것들.
CROSS_CHECK = [
    ("Beef Carcass", "beef"),
    ("Pork Carcass", "pork"),
    ("116A Chuck Roll neck-off", "beef_116"),
    ("123A Short Rib", "pork_123a"),
]

# 지표별 정상 범위. 벗어나면 파싱이 틀렸을 가능성이 크다.
RANGES = {
    ("beef", "cutout"): (1.5, 6),
    ("pork", "cutout"): (0.4, 2.5),
    ("beef", "live_price"): (80, 400),
    ("pork", "live_price"): (20, 200),
    ("beef", "slaughter"): (300_000, 800_000),
    ("pork", "slaughter"): (1_000_000, 3_500_000),
    ("beef", "production"): (250_000_000, 700_000_000),
    ("pork", "production"): (300_000_000, 800_000_000),
}

# 사후 조정되는 지표. 전주값이 어긋나도 정상이다.
REVISED = {"production", "slaughter"}


def load(path):
    try:
        with open(path, newline="", encoding="utf-8") as fp:
            return list(csv.DictReader(fp))
    except FileNotFoundError:
        return []


def check_against_api():
    pdf = defaultdict(dict)
    for row in load(CUTS):
        pdf[row["week"]][row["item"]] = float(row["value"])
    api = {row["date"]: row for row in load(API)}
    if not api:
        print("  API 파일이 없어 건너뜀")
        return 0

    failures = 0
    for item, column in CROSS_CHECK:
        same = diff = skip = 0
        examples = []
        for week, values in sorted(pdf.items()):
            if item not in values or week not in api or not api[week].get(column):
                skip += 1
                continue
            a, b = values[item], float(api[week][column])
            if abs(a - b) < 0.005:
                same += 1
            else:
                diff += 1
                if len(examples) < 3:
                    examples.append(f"{week} PDF {a} / API {b}")
        # 파싱이 체계적으로 틀리면 수백 건이 어긋난다. 한두 건은 출처 간 정정이다
        # (예: 2020-02-26 호가 1/25 지육값만 정정해 실었고 API 는 원값을 유지).
        # 그래서 건수가 아니라 비율로 판정한다.
        limit = max(2, int(same * 0.01))
        verdict = "정정으로 보임" if diff <= limit else "파싱 오류 의심"
        if diff > limit:
            failures += diff
        print(f"  {item[:26]:26} 일치 {same:4}  불일치 {diff:3}  대조불가 {skip:4}"
              + (f"   <- {verdict}" if diff else ""))
        for line in examples:
            print(f"      {line}")
    return failures


def check_chain():
    series = defaultdict(dict)
    for row in load(STATS):
        prev = float(row["prev"]) if row["prev"] else None
        series[(row["species"], row["metric"])][row["week"]] = (float(row["value"]), prev)

    ok = revised = suspect = 0
    examples = []
    for key, weeks in sorted(series.items()):
        order = sorted(weeks)
        for before, after in zip(order, order[1:]):
            gap = (dt.date.fromisoformat(after) - dt.date.fromisoformat(before)).days
            if gap != 7:
                continue  # 호가 빠진 구간은 어긋나는 게 당연하다
            value, stated = weeks[before][0], weeks[after][1]
            if stated is None:
                continue
            if abs(value - stated) / max(abs(value), 1) < 0.005:
                ok += 1
            elif key[1] in REVISED:
                revised += 1
            else:
                suspect += 1
                if len(examples) < 5:
                    examples.append(f"{key[0]}/{key[1]} {after}: 기재 {stated:,.2f} / 직전 {value:,.2f}")

    total = ok + revised + suspect
    print(f"  일치 {ok} / USDA 조정으로 설명됨 {revised} / 설명 안 됨 {suspect}"
          f"  ({100 * ok / max(total, 1):.1f}% 일치)")
    for line in examples:
        print(f"      {line}")
    return suspect


def check_ranges():
    values = defaultdict(list)
    for row in load(STATS):
        values[(row["species"], row["metric"])].append((row["week"], float(row["value"])))

    failures = 0
    for key, bounds in RANGES.items():
        rows = values.get(key)
        if not rows:
            continue
        low, high = bounds
        out = [r for r in rows if not low <= r[1] <= high]
        failures += len(out)
        mark = "!" if out else " "
        span = f"{min(v for _, v in rows):,.2f} ~ {max(v for _, v in rows):,.2f}"
        print(f" {mark}{key[0]:5}{key[1]:12} {span:>34}  n={len(rows):4}"
              + (f"  범위 밖 {len(out)}건 {out[:2]}" if out else ""))
    return failures


def main():
    print("[1] JSON API 대조 (가장 강한 근거)")
    api_fail = check_against_api()
    print("\n[2] 전주값 체인")
    chain_fail = check_chain()
    print("\n[3] 값 범위")
    range_fail = check_ranges()

    print()
    if api_fail or range_fail:
        print(f"실패: API 불일치 {api_fail}건, 범위 밖 {range_fail}건 — 파서를 고쳐야 한다")
        return 1
    if chain_fail:
        print(f"주의: 조정으로 설명 안 되는 전주값 불일치 {chain_fail}건 — 확인 필요")
        return 0
    print("모든 검증 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
