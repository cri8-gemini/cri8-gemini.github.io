"""USMEF 주간 시세 수집기.

http://usmef.lobonine.gethompy.com/main/mobile_json.php (code=10) 에서
연도별 주간 시세를 받아 하나의 CSV 로 합친다.

이 서버는 https 를 받지 않고(평문 http 전용) CORS 헤더도 주지 않는다. 그래서
브라우저에서 직접 부를 수 없고, 이렇게 빌드 시점에 받아 두어야 한다.

usage:
    python scripts/collect_usmef.py                 # 2005~올해
    python scripts/collect_usmef.py --from 2015     # 시작 연도 지정
    python scripts/collect_usmef.py -o out.csv
"""

import argparse
import csv
import datetime as dt
import json
import sys
import time
import urllib.parse
import urllib.request

URL = "http://usmef.lobonine.gethompy.com/main/mobile_json.php"

# 응답 필드 -> CSV 컬럼
FIELDS = {
    "priceBeef": "beef",      # 소고기 종합
    "price116": "beef_116",   # 소고기 116A
    "pricePig": "pork",       # 돼지고기 종합
    "price123a": "pork_123a", # 돼지고기 123A
}


def fetch_year(year):
    """해당 연도의 주간 시세 목록을 반환. 데이터 없으면 빈 리스트.

    주의: 이 API 는 보유 범위 밖의 연도를 요청해도 오류를 내지 않고 최신 연도
    데이터를 그대로 돌려준다 (2005 를 요청하면 2025 데이터가 온다). 다행히
    응답에 실제로 응답한 연도가 thisYear 로 실려 오므로, 요청한 연도와 다르면
    버린다. 이 검증이 없으면 존재하지 않는 과거 구간이 최신 데이터의 복제본으로
    채워진다.
    """
    body = urllib.parse.urlencode({"code": "10", "thisYear": str(year)}).encode()
    req = urllib.request.Request(
        URL,
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "Mozilla/5.0",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        # Content-Type 이 text/html 로 오므로 강제 파싱
        payload = json.loads(resp.read().decode("utf-8"))

    if payload.get("resultCode") != "0":
        return []

    answered = str(payload.get("thisYear", "")).strip()
    if answered and answered != str(year):
        print(f"  ! {year} 요청에 {answered} 응답 — 보유 범위 밖으로 보고 버림", file=sys.stderr)
        return []

    return payload.get("data", [])


def to_rows(year, data):
    """API 행(priceDate="7/11")을 ISO 날짜 행으로 변환."""
    rows = []
    for item in data:
        raw = item.get("priceDate", "").strip()
        try:
            month, day = (int(x) for x in raw.split("/"))
            date = dt.date(year, month, day)
        except (ValueError, TypeError):
            print(f"  ! 날짜 파싱 실패: {year} {raw!r}", file=sys.stderr)
            continue

        row = {"date": date.isoformat()}
        for src, dst in FIELDS.items():
            value = item.get(src, "").strip()
            row[dst] = value if value else ""
        rows.append(row)
    return rows


def main():
    this_year = dt.date.today().year
    parser = argparse.ArgumentParser()
    # 확인된 보유 범위는 2010 년부터. 더 이전을 요청하면 fetch_year 가 걸러낸다.
    parser.add_argument("--from", dest="start", type=int, default=2010)
    parser.add_argument("--to", dest="end", type=int, default=this_year)
    parser.add_argument("-o", "--out", default="data/usmef_weekly.csv")
    args = parser.parse_args()

    all_rows = []
    for year in range(args.start, args.end + 1):
        try:
            data = fetch_year(year)
        except Exception as exc:  # 네트워크/파싱 실패는 해당 연도만 건너뛴다
            print(f"{year}: 실패 ({exc})", file=sys.stderr)
            continue

        rows = to_rows(year, data)
        print(f"{year}: {len(rows)}건")
        all_rows.extend(rows)
        time.sleep(0.3)

    all_rows.sort(key=lambda r: r["date"])

    columns = ["date", *FIELDS.values()]
    with open(args.out, "w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=columns)
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"\n총 {len(all_rows)}건 -> {args.out}")
    if all_rows:
        print(f"기간: {all_rows[0]['date']} ~ {all_rows[-1]['date']}")


if __name__ == "__main__":
    main()
