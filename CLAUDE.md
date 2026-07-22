# CLAUDE.md

텍사스 로드하우스(TXRH) 주가와 미국 육류 시세를 비교하는 정적 사이트.
배포처는 https://cri8-gemini.github.io/ 이고, 저장소가 곧 사용자 GitHub Pages 저장소다
(`cri8-gemini/cri8-gemini.github.io`).

사용자와의 대화는 한국어로 한다.

## 무엇을 하는 프로젝트인가

원가(육류 시세)가 주가에 반영되는지 눈으로 보려는 것이다. 두 데이터를 주 단위로
맞춰 지수화해 겹쳐 보고, 시차를 줘 가며 상관을 계산한다.

**현재까지의 결론: 뚜렷한 관계가 없다.** 전 구간 주간 변화율 기준으로 네 지표 모두
시차를 줘도 상관이 −0.16 ~ +0.10 범위이고, 시차마다 부호가 뒤집혀 일관된 패턴이
없다. 관측치가 850개대라 잡음 띠가 ±0.07로 좁아 몇몇이 띠를 벗어나지만, 시차 8개를
한꺼번에 보면 하나쯤은 우연히 튀어나온다. 관계로 읽으면 안 된다.

아직 안 해본 것: 주간이 아니라 **분기 평균으로 묶어서** 보기. 주간 시세가 분기 실적을
거쳐 주가에 반영되는 경로라면 주 단위로는 안 잡힐 수 있다.

## 구조

```
scripts/collect_usmef.py   육류 시세 -> data/usmef_weekly.csv
scripts/collect_txrh.py    TXRH 주봉 -> data/txrh_weekly.csv
scripts/build_site.py      ISO 주차로 병합 -> index.html, data/merged_weekly.csv
scripts/template.html      페이지 원본. 데이터가 빌드 시점에 주입된다
```

전체 재생성:

```bash
python scripts/collect_usmef.py
python scripts/collect_txrh.py
python scripts/build_site.py
```

**`index.html` 을 직접 고치지 말 것.** 생성물이다. `scripts/template.html` 을 고치고
`build_site.py` 를 다시 돌린다. 템플릿의 `/*__DATA__*/null` 자리에 JSON 이 들어간다.

## 데이터 함정 (전부 실제로 당한 것들)

지우면 조용히 틀린 차트가 나온다. 수집기의 방어 코드는 장식이 아니다.

- **범위 밖 연도를 요청하면 오류 대신 최신 연도 데이터가 온다.** `thisYear=2005` 를
  요청하면 2025 년 데이터가 그대로 돌아온다. 처음 수집했을 때 2005~2009 구간이 통째로
  2025 년의 복제본이었고, 차트에 2010 년 수직 절벽으로 나타나서 발견했다. 응답에 실제
  응답 연도가 `thisYear` 로 실려 오므로 `collect_usmef.py` 가 대조해 버린다.
  **확인된 실제 보유 범위는 2010 년부터.**
- **결측이 빈 값이 아니라 `0.00` 으로 온다.** 2017-10-07 의 `priceBeef` 가 그렇고 같은
  행의 나머지 항목은 정상이다. `build_site.py` 의 `to_float` 가 0 이하를 결측 처리한다.
- **Yahoo 의 `adjClose` 는 요청마다 4째 자리가 흔들린다.** 수정계수를 매번 재계산하는
  탓이다. 그대로 저장하면 값이 안 바뀐 날에도 57 행이 바뀐 diff 가 매일 커밋된다.
  소수점 2 자리로 자른다.
- **CSV 는 LF 로 쓴다.** `csv` 모듈 기본 lineterminator 가 CRLF 라, 윈도우 로컬과
  리눅스 러너가 같은 값에 다른 바이트를 만든다. 첫 자동 갱신에서 CSV 두 개가 통째로
  (1,729 줄) 다시 커밋됐다. writer 에 `lineterminator="\n"`, `.gitattributes` 로 이중
  고정.
- 2020 년 5 월 소고기 급등은 **실제 값**이다 (코로나 도축장 셧다운). 주간 25% 를 넘는
  비정상 점프는 전 구간에 없다.

수집기를 손댔으면 **연속 두세 번 돌려서 `git diff -- data` 가 비는지** 확인할 것.
비지 않으면 위 같은 잡음이 새로 들어온 것이다.

## 원본 API

`POST http://usmef.lobonine.gethompy.com/main/mobile_json.php`, body `code=10&thisYear=`

브라우저에서 직접 못 부른다. **평문 http 전용**(https 는 핸드셰이크 실패)이라 https
페이지에서 mixed content 로 막히고, **CORS 헤더도 없다.** 그래서 빌드 시점에 받아
페이지에 박아 넣는 구조다. 이건 우회 불가능하니 "실시간으로 불러오자"는 방향으로
되돌아가지 말 것.

`code` 값은 10 이 시세다. 1·11 은 부위 정보, 3~5 는 앱진, 6~7 은 공지, 13~14 는 관세표.

주가는 Yahoo 차트 API (`query1.finance.yahoo.com/v8/finance/chart/TXRH`, `interval=1wk`).
외부 패키지 없이 표준 라이브러리로 받는다 — CI 에서 의존성 설치가 없다.

## 차트 설계 원칙

바꾸기 전에 이유를 읽을 것. 전부 의도된 제약이다.

- **축을 두 개 쓰지 않는다.** 주가와 시세는 단위도 자릿수도 다르지만, 이중 축은 눈금을
  어떻게 잡느냐로 상관관계를 있어 보이게도 없어 보이게도 만든다. 구간 시작을 100 으로
  맞춘 지수를 한 축에 올린다.
- **세로축 기본은 로그.** 전 구간 기준 TXRH 는 21 배, 육류는 3 배 올랐다. 선형 축에서는
  육류 선이 바닥에 눌려 비교가 안 된다.
- **상관은 수준이 아니라 주간 변화율로.** 둘 다 장기 우상향이라 수준 상관은 아무 관계가
  없어도 1 에 가깝게 나온다.
- **잡음 띠는 시차마다 따로 계산한다.** 시차가 클수록 겹치는 구간이 짧아져 관측치가 줄고
  띠가 넓어진다. 하나로 통일하면 관측치가 많은 시차를 과하게 깎아내린다.
- **한 번에 두 계열만.** 색은 파랑(주가)·주황(육류) 고정이고 CVD 검증을 통과한 조합이다.
  계열을 늘리려 했지만 4 색 이상은 색각 이상 분리 기준을 통과하는 조합이 없었다.
  늘려야 하면 색으로 구분하지 말고 facet 으로 쪼갤 것.
- 선 끝 직접 라벨, 막대 값 직접 표기 — 색만으로 계열을 구분하지 않는다.

## 배포

GitHub Actions 가 매일 06:00 KST 에 수집 → **데이터가 바뀐 날만** `data/` 를 커밋 →
사이트를 빌드해 Pages 아티팩트로 배포한다. `workflow_dispatch` 로 수동 실행도 된다.

Actions 는 `index.html` 을 **커밋하지 않는다.** 생성물이라 로컬 작업분과 충돌한다
(실제로 rebase 충돌이 났다). 배포는 아티팩트로만 한다.

동작 조건 두 가지:
- Settings → Actions → General → Workflow permissions = **Read and write**
- Settings → Pages → Source = **GitHub Actions**

## 이 저장소의 git 설정

사용자는 GitHub 계정이 둘이고, 전역 자격증명(`git:https://github.com`)은 **다른
계정**(`cri8now-alt`)으로 잡혀 있다. 그대로 푸시하면 403 이 난다.

그래서 원격 URL 에 계정을 박아 자격증명을 분리해 뒀다:
`https://cri8-gemini@github.com/cri8-gemini/cri8-gemini.github.io.git`

전역 설정과 다른 계정의 자격증명은 **건드리지 말 것.** 커밋 이름/이메일도 이 저장소
한정으로 `cri8-gemini` + noreply 주소로 잡혀 있다.

## 이 환경에서의 확인 방법

`gh` CLI 와 playwright 는 없다. 렌더링 확인은 Edge 헤드리스로 한다:

```bash
"/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe" --headless=new \
  --disable-gpu --no-sandbox --hide-scrollbars --user-data-dir=/c/tmp/edgeprofile \
  --window-size=1000,1300 --virtual-time-budget=4000 \
  --screenshot=/c/tmp/shot.png "file:///c:/work/chart/index.html"
```

`--screenshot` 대신 `--dump-dom` 을 쓰면 JS 실행 결과를 텍스트로 확인할 수 있다.
차트를 고쳤으면 **반드시 실제로 렌더해서 눈으로 볼 것.** 지금까지 잡은 버그
(2010 년 절벽, `-0` 눈금, 바닥에 눌린 선) 는 전부 코드가 아니라 그림에서 발견됐다.
