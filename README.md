# TXRH vs 미국 육류 시세

텍사스 로드하우스(TXRH) 주가와 미국 육류 시세를 같은 기준으로 비교하는 정적 페이지입니다.

**https://cri8-gemini.github.io/**

매일 06:00 KST 에 GitHub Actions 가 두 소스를 다시 받아 값이 바뀐 날만 커밋합니다.

## 구조

```
scripts/collect_usmef.py   육류 시세 수집 -> data/usmef_weekly.csv
scripts/collect_txrh.py    TXRH 주가 수집 -> data/txrh_weekly.csv
scripts/build_site.py      두 CSV 를 ISO 주차로 병합 -> index.html, data/merged_weekly.csv
scripts/template.html      페이지 템플릿 (데이터가 빌드 시점에 주입된다)
```

로컬에서 전체를 다시 만들려면:

```bash
python scripts/collect_usmef.py
python scripts/collect_txrh.py
python scripts/build_site.py
```

## 데이터 소스

**육류 시세** — `usmef.lobonine.gethompy.com/main/mobile_json.php` (`code=10`), 주 1회 갱신.

이 API 를 브라우저에서 직접 부를 수 없어서 빌드 시점에 받아 둡니다. 평문 http 전용이라
https 페이지에서는 mixed content 로 막히고, CORS 헤더도 없습니다.

**주가** — Yahoo Finance 차트 API 주봉. 배당·분할이 반영된 수정종가를 씁니다.

## 알아둘 것 (데이터 함정)

수집기에 방어 코드가 들어간 이유입니다. 지우면 조용히 틀린 차트가 나옵니다.

- **보유 범위 밖 연도를 요청하면 오류 대신 최신 연도 데이터가 온다.** `thisYear=2005` 를
  요청하면 2025 년 데이터가 그대로 돌아옵니다. 응답에 실제 응답 연도가 `thisYear` 로
  실려 오므로 `collect_usmef.py` 가 이를 대조해 버립니다. 확인된 실제 보유 범위는
  **2010 년부터**입니다.
- **결측이 빈 값이 아니라 `0.00` 으로 온다.** 예를 들어 2017-10-07 의 `priceBeef` 는
  `0.00` 인데 같은 행의 나머지 항목은 정상입니다. `build_site.py` 가 0 이하를 결측으로
  처리합니다.
- 2020 년 5 월 소고기 급등은 실제 값입니다 (코로나 도축장 셧다운).

## 차트에 대해

- 주가와 육류 시세는 단위도 자릿수도 달라 **축을 두 개 쓰지 않습니다.** 눈금을 어떻게
  잡느냐로 상관관계를 있어 보이게도 없어 보이게도 만들 수 있기 때문입니다. 대신 구간
  시작을 100 으로 맞춘 지수를 한 축에 올립니다.
- 기본 세로축은 **로그**입니다. 두 계열의 상승폭 차이가 커서(전 구간 기준 21배 vs 3배)
  선형 축에서는 육류 선이 바닥에 눌립니다. 로그 축에서는 세로 거리가 곧 변화율입니다.
- 상관계수는 수준이 아니라 **주간 변화율**로 계산합니다. 둘 다 장기 우상향이라 수준
  상관은 아무 관계가 없어도 1 에 가깝게 나옵니다.
