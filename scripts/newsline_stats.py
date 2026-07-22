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

# 카드 열의 x 는 고정이 아니다. 2026년 호는 소·돼지 카드가 모두 오른쪽 열에
# 있지만, 2024년 호는 돼지 카드가 왼쪽 열(폭의 8%)에 있다. 그래서 좌표를 박아
# 두면 절반을 놓친다.
#
# 대신 "카드는 한 섹션에 4장이 같은 x 로 세로로 늘어선다"는 성질로 열을 찾는다.
# 본문에 우연히 나온 '컷아웃' 같은 낱말은 같은 x 에 여럿 모이지 않아 걸러진다.
COLUMN_TOLERANCE = 8       # 같은 열로 볼 x 차이
MIN_CARDS_PER_COLUMN = 3   # 한 섹션은 카드 4장이다
VALUE_WIDTH = 0.19         # 라벨 x 부터 이만큼(폭 대비)이 값 자리. 그 밖은 증감폭.
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


def species_of(word, anchors):
    """카드의 축종을 정한다.

    영문 섹션 헤더('U.S. beef market trends')로 판단했더니 2024년 호에서
    실패했다. 연도마다 레이아웃이 바뀌므로 PDF 안에서 스스로 성립하는 성질만
    쓴다 — 한 섹션에는 생우(소) 또는 생돈(돼지) 카드가 정확히 하나씩 있으니,
    같은 열에서 세로로 가장 가까운 그 카드가 이 카드의 축종이다.
    """
    if word[4] == "생우":
        return "beef"
    if word[4] == "생돈":
        return "pork"

    same_column = [a for a in anchors
                   if a[4] in ("생우", "생돈") and abs(a[0] - word[0]) <= COLUMN_TOLERANCE]
    if not same_column:
        return None
    nearest = min(same_column, key=lambda a: abs(a[1] - word[1]))
    return "beef" if nearest[4] == "생우" else "pork"


# 단위 라벨에는 숫자가 붙어 있다 — '100파운드당가격', '1파운드당가격'.
# 레이아웃에 따라 이게 값 자리 안으로 들어오는데(2024년 호의 생우 카드),
# 그대로 두면 생우 가격이 통째로 100 으로 읽힌다.
UNIT_LABEL = re.compile(r"당가격|단위")

# 이 PDF 는 일부 한글 음절을 사용자 정의 영역(PUA) 글리프로 넣는다.
# 그래서 '100파운드당가격' 이 '100파운드당가격' 으로 추출되고, 순진하게
# 패턴을 맞추면 빗나간다. 비교 전에 걷어낸다.
PUA = re.compile(r"[-]")
clean = lambda text: PUA.sub("", text)


def row_text(words, y0, y1, lo, hi):
    picked = [clean(w[4]) for w in sorted(words, key=lambda w: w[0])
              if y0 < w[1] < y1 and lo <= w[0] < hi]
    return " ".join(t for t in picked if not UNIT_LABEL.search(t))


def card_columns(words):
    """카드 라벨이 3개 이상 같은 x 에 늘어선 곳만 카드 열로 본다."""
    xs = sorted(w[0] for w in words if w[4] in CARDS)
    columns, group = [], []
    for x in xs:
        if group and x - group[-1] > COLUMN_TOLERANCE:
            if len(group) >= MIN_CARDS_PER_COLUMN:
                columns.append(sum(group) / len(group))
            group = []
        group.append(x)
    if len(group) >= MIN_CARDS_PER_COLUMN:
        columns.append(sum(group) / len(group))
    return columns


def extract_cards(words, width):
    columns = card_columns(words)
    anchors = [w for w in words if w[4] in CARDS]
    out = []
    for word in words:
        if word[4] not in CARDS:
            continue
        if not any(abs(word[0] - c) <= COLUMN_TOLERANCE for c in columns):
            continue
        y = word[1]
        lo, hi = word[0] - 5, word[0] + VALUE_WIDTH * width
        value = parse_korean_number(row_text(words, y + VALUE_BAND[0], y + VALUE_BAND[1], lo, hi))
        prev_raw = row_text(words, y + PREV_BAND[0], y + PREV_BAND[1], lo, hi)
        # 진짜 카드는 반드시 '전 주 …' 줄을 갖는다. 본문에 우연히 같은 열로
        # 떨어진 낱말을 거르는 기준으로 쓴다.
        if "전" not in prev_raw:
            continue
        prev = parse_korean_number(prev_raw)
        species = species_of(word, anchors)
        if value is None or species is None:
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
# 문구가 해마다 다르다. 숫자 앞에 서술이 끼고("전 주 대비 14% 감소한 28,920톤"),
# "그중"/"그 중", "32,800 톤"처럼 띄어쓰기도 흔들린다. 그래서 숫자를 바로
# 집으려 하지 말고 "톤" 앞의 숫자를 찾는다.
EXPORT = re.compile(
    r"(\d{1,2})월\s*(\d{1,2})일부터\s*(?:(\d{1,2})월\s*)?(\d{1,2})일까지\s*"
    r"미국의\s*(소고기|돼지고기)\s*수출량은[^톤]{0,60}?([\d,]+)\s*톤"
    r".{0,80}?한국으로의\s*수출량은[^톤]{0,60}?([\d,]+)\s*톤",
    re.S,
)


def extract_exports(text, issue_date):
    flat = re.sub(r"\s+", " ", clean(text))
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
