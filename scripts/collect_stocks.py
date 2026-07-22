"""주간 주가 수집기.

data/stocks/tickers.txt 에 적힌 종목을 각각 data/stocks/<티커>.csv 로 저장한다.
종목마다 파일을 나누는 이유는 diff 다 — 한 파일에 몰아넣으면 매일 모든 종목의
최신 행이 함께 바뀌어 어느 종목이 갱신됐는지 안 보이고, 한 종목 수집이 실패하면
나머지까지 휘말린다.

Yahoo Finance 차트 API 를 쓴다. 외부 패키지 없이 표준 라이브러리만 쓰므로
CI 에서 설치할 의존성이 없다.

수익률 비교에는 배당·액면분할이 반영된 adjClose 를 쓴다. close 는 참고용.

usage:
    python scripts/collect_stocks.py
    python scripts/collect_stocks.py --ticker DRI
"""

import argparse
import csv
import datetime as dt
import json
import os
import sys
import time
import urllib.parse
import urllib.request

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
STOCK_DIR = "data/stocks"
TICKERS_FILE = os.path.join(STOCK_DIR, "tickers.txt")

# 육류 시세가 2010년부터라 시작점을 맞춘다 (그 이전은 원본 API 에 없다).
DEFAULT_START = dt.date(2009, 12, 1)


def read_tickers():
    with open(TICKERS_FILE, encoding="utf-8") as fp:
        return [line.strip() for line in fp
                if line.strip() and not line.startswith("#")]


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
        # 소수점 2자리로 자른다. Yahoo 가 요청마다 수정계수를 재계산해서
        # adjClose 4째 자리가 ±0.0001 씩 흔들리는데, 그대로 저장하면 값이
        # 그대로인 날에도 수십 행이 바뀐 diff 가 매일 커밋된다.
        rows.append({
            "date": dt.date.fromtimestamp(stamp).isoformat(),
            "close": f"{close:.2f}" if close is not None else "",
            "adj_close": f"{adj_close:.2f}" if adj_close is not None else "",
            "volume": volumes[i] if i < len(volumes) and volumes[i] is not None else "",
        })
    return rows


def collect(ticker):
    rows = to_rows(fetch(ticker, DEFAULT_START))
    if not rows:
        raise RuntimeError("데이터 없음")

    path = os.path.join(STOCK_DIR, f"{ticker}.csv")
    with open(path, "w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=["date", "close", "adj_close", "volume"],
                                lineterminator="\n")  # LF 고정 — 러너와 로컬을 맞춘다
        writer.writeheader()
        writer.writerows(rows)
    return path, rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", help="이 종목만 수집 (기본: tickers.txt 전부)")
    args = parser.parse_args()

    os.makedirs(STOCK_DIR, exist_ok=True)
    tickers = [args.ticker] if args.ticker else read_tickers()

    failed = 0
    for ticker in tickers:
        try:
            path, rows = collect(ticker)
        except Exception as exc:
            # 한 종목이 실패해도 나머지는 계속한다.
            print(f"{ticker}: 수집 실패 ({exc})", file=sys.stderr)
            failed += 1
            continue
        print(f"{ticker}: {len(rows)}건  {rows[0]['date']} ~ {rows[-1]['date']} -> {path}")
        time.sleep(0.3)

    return 1 if failed == len(tickers) else 0


if __name__ == "__main__":
    sys.exit(main())
