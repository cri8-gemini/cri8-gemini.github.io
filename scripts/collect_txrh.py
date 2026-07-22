"""TXRH(텍사스 로드하우스) 주간 주가 수집기.

Yahoo Finance 차트 API 에서 주봉을 받아 CSV 로 저장한다. 외부 패키지 없이
표준 라이브러리만 쓴다 (CI 에서 의존성 설치가 필요 없도록).

수익률 비교에는 배당·액면분할이 반영된 adjClose 를 쓴다. close 는 참고용.

usage:
    python scripts/collect_txrh.py
    python scripts/collect_txrh.py --ticker HRL -o data/hrl_weekly.csv
"""

import argparse
import csv
import datetime as dt
import json
import sys
import urllib.parse
import urllib.request

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"

# 육류 시세가 2010년부터라 시작점을 맞춘다 (그 이전은 원본 API 에 없다).
DEFAULT_START = dt.date(2009, 12, 1)


def fetch(ticker, start):
    params = urllib.parse.urlencode({
        "period1": int(dt.datetime.combine(start, dt.time()).timestamp()),
        "period2": int(dt.datetime.now().timestamp()) + 86400,
        "interval": "1wk",
    })
    req = urllib.request.Request(
        f"{CHART_URL.format(ticker=ticker)}?{params}",
        headers={"User-Agent": "Mozilla/5.0"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode("utf-8"))

    chart = payload.get("chart") or {}
    if chart.get("error"):
        raise RuntimeError(f"Yahoo 오류: {chart['error']}")

    result = (chart.get("result") or [None])[0]
    if not result:
        raise RuntimeError("결과가 비어 있음")
    return result


def to_rows(result):
    stamps = result.get("timestamp") or []
    quote = (result["indicators"].get("quote") or [{}])[0]
    adj = (result["indicators"].get("adjclose") or [{}])[0].get("adjclose") or []
    closes = quote.get("close") or []
    volumes = quote.get("volume") or []

    rows = []
    for i, stamp in enumerate(stamps):
        close = closes[i] if i < len(closes) else None
        adj_close = adj[i] if i < len(adj) else None
        # 거래가 없던 주는 null 로 온다 — 버린다.
        if close is None and adj_close is None:
            continue
        rows.append({
            "date": dt.date.fromtimestamp(stamp).isoformat(),
            "close": f"{close:.4f}" if close is not None else "",
            "adj_close": f"{adj_close:.4f}" if adj_close is not None else "",
            "volume": volumes[i] if i < len(volumes) and volumes[i] is not None else "",
        })
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", default="TXRH")
    parser.add_argument("-o", "--out", default="data/txrh_weekly.csv")
    args = parser.parse_args()

    try:
        result = fetch(args.ticker, DEFAULT_START)
    except Exception as exc:
        print(f"{args.ticker}: 수집 실패 ({exc})", file=sys.stderr)
        return 1

    rows = to_rows(result)
    if not rows:
        print(f"{args.ticker}: 데이터 없음", file=sys.stderr)
        return 1

    with open(args.out, "w", newline="", encoding="utf-8") as fp:
        # LF 고정 — 이유는 collect_usmef.py 참고
        writer = csv.DictWriter(fp, fieldnames=["date", "close", "adj_close", "volume"],
                                lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    print(f"{args.ticker}: {len(rows)}건 -> {args.out}")
    print(f"기간: {rows[0]['date']} ~ {rows[-1]['date']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
