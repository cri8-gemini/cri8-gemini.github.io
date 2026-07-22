"""NEWSLINE PDF 의 시장동향 지표를 뽑는다 (가격표가 아닌 쪽).

오른쪽 열의 카드 네 장(컷아웃 / 도축두수 / 생산량 / 생우·생돈)과 본문 서술의
수출량을 가져온다. 카드는 이런 모양이다:

    y+0     도축두수                        단위 : 두
    y+53    52만 5,000두            0.8 %
    y+133   전 주 52만 9,000두

증감 방향(▲▼)은 글자가 아니라 도형이라 추출되지 않는다. 대신 값과 전주값이
둘 다 있으니 방향은 계산한다.
"""

import datetime as dt
import re

# 카드 라벨 -> (지표 이름, 축종). 생우/생돈만 축종이 라벨로 드러난다.
CARDS = {
    "컷아웃": "cutout",
    "도축두수": "slaughter",
    "생산량": "production",
    "생우": "live_price",
    "생돈": "live_price",
}

# 좌표는 페이지 폭에 대한 비율로 잡는다. 호마다 폭이 1080 과 800 두 가지다.
# 카드 라벨은 폭의 65.5% 지점에 왼쪽 정렬돼 있고, 본문이 우연히 그 열에 걸치는
# 경우가 있어 좁게 조여야 가짜 카드가 안 생긴다.
CARD_X = (0.645, 0.668)
# 값을 읽을 가로 범위. 왼쪽 경계가 없으면 본문 숫자가, 오른쪽을 넓게 잡으면
# 증감폭(0.8 %, $ 0.12)이 본값에 섞여 들어온다.
VALUE_X = (0.645, 0.83)
VALUE_BAND = (20, 85)      # 라벨 아래 값이 오는 구간
PREV_BAND = (95, 175)      # '전 주 …' 가 오는 구간

NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")
UNITS = {"억": 10 ** 8, "만": 10 ** 4}


def parse_korean_number(text):
    """'4억 6,500만' -> 465000000 · '52만 5,000두' -> 525000 · '$ 3.71' -> 3.71"""
    text = text.replace(",", "")
    total, plain = 0, None
    for match in re.finditer(r"(\d+(?:\.\d+)?)\s*([억만]?)", text):
        value, unit = float(match.group(1)), match.group(2)
        if unit:
            total += value * UNITS[unit]
        else:
            plain = value
    if total:
        return total + (plain or 0)
    return plain


def sections(words):
    """'U.S. beef|pork market trends' 헤더의 y 를 찾아 구간을 나눈다."""
    found = []
    for word in words:
        if word[4] not in ("beef", "pork"):
            continue
        line = [w[4] for w in words if abs(w[1] - word[1]) < 6]
        if "trends" in line and "U.S." in line:
            found.append((word[1], word[4]))
    return sorted(found)


def species_at(marks, y):
    """그 카드보다 위에 있는 가장 가까운 섹션 헤더의 축종."""
    current = None
    for mark_y, name in marks:
        if mark_y <= y:
            current = name
    return current


def row_text(words, y0, y1, width):
    lo, hi = VALUE_X[0] * width, VALUE_X[1] * width
    picked = [w for w in words if y0 < w[1] < y1 and lo <= w[0] < hi]
    return " ".join(w[4] for w in sorted(picked, key=lambda w: w[0]))


def extract_cards(words, width):
    marks = sections(words)
    lo, hi = CARD_X[0] * width, CARD_X[1] * width
    out = []
    for word in words:
        if word[4] not in CARDS or not lo <= word[0] <= hi:
            continue
        y = word[1]
        value = parse_korean_number(row_text(words, y + VALUE_BAND[0], y + VALUE_BAND[1], width))
        prev_raw = row_text(words, y + PREV_BAND[0], y + PREV_BAND[1], width)
        prev = parse_korean_number(prev_raw) if "전" in prev_raw else None
        if value is None:
            continue
        species = "beef" if word[4] == "생우" else "pork" if word[4] == "생돈" \
            else species_at(marks, y)
        if not species:
            continue
        out.append({"species": species, "metric": CARDS[word[4]],
                    "value": value, "prev": prev})
    return out


# 본문: "7월 3일부터 9일까지 미국의 소고기 수출량은 25,220톤을 기록했고 그중
# 한국으로의 수출량은 1,800톤으로 집계되었다."
#
# 수출량은 다른 지표보다 훨씬 늦게 집계된다. 위 예에서 가격표의 최신 주는
# 7/18 인데 수출 집계는 7/9 까지다. 그래서 카드 지표와 같은 주로 묶으면 안 되고,
# 본문이 밝힌 기간의 끝 날짜를 쓴다.
EXPORT = re.compile(
    r"(\d{1,2})월\s*(\d{1,2})일부터\s*(?:(\d{1,2})월\s*)?(\d{1,2})일까지\s*"
    r"미국의\s*(소고기|돼지고기)\s*수출량은\s*([\d,]+)\s*톤.{0,40}?"
    r"한국으로의\s*수출량은\s*([\d,]+)\s*톤",
    re.S,
)


def extract_exports(text, issue_date):
    flat = re.sub(r"\s+", " ", text)
    out = []
    for m in EXPORT.finditer(flat):
        start_month, _, end_month, end_day, kind, total, korea = m.groups()
        month = int(end_month or start_month)
        try:
            week = dt.date(issue_date.year, month, int(end_day))
        except ValueError:
            continue
        if week > issue_date:                      # 연말 호는 전년도를 가리킨다
            week = dt.date(issue_date.year - 1, month, int(end_day))
        species = "beef" if kind == "소고기" else "pork"
        for metric, value in (("export_total", total), ("export_korea", korea)):
            out.append({"species": species, "metric": metric,
                        "value": float(value.replace(",", "")),
                        "prev": None, "week": week.isoformat()})
    return out


def extract(page, issue_date):
    words = page.get_text("words")
    return (extract_cards(words, page.rect.width)
            + extract_exports(page.get_text(), issue_date))
