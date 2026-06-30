"""scraper/dart HTML 파서 회귀 테스트 (네트워크 없음 · 합성 픽스처).

이 프로그램에서 가장 깨지기 쉬운 코드는 38커뮤니케이션 HTML / DART 문서 파싱이다.
사이트 구조 변화나 특수 종목(재상장 '성명' 라벨, 거대 wrapper 표, 소계 오매칭 등)에서
조용히 틀린 숫자가 나오지 않도록, 실제 구조를 본뜬 최소 픽스처로 동작을 고정한다.

※ 픽스처는 실제 사이트 HTML 전체가 아니라, 각 파서가 의존하는 표 구조와
  이번까지 수정한 함정들을 압축한 합성본이다(저작권·인코딩·용량 회피, 결정적 실행).
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from bs4 import BeautifulSoup  # noqa: E402

from analyzer import scraper, dart  # noqa: E402


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


# ===========================================================================
# 유통가능주식수 — _parse_circulating / _circ_pair_in_cells
# ===========================================================================
def test_parse_circulating_prefers_total_over_subtotal():
    # 함정: '소계' 행의 (공모전%+공모후%)가 우연히 ~100%라 먼저 오매칭될 수 있다.
    # → '합계' 행을 우선 탐색해야 한다. (스트라드비전류 53.65%+46.45% 케이스)
    html = """
    <table>
      <tr><th>주주명</th><th>공모전</th><th>지분율</th><th>공모후 유통가능물량</th><th>지분율</th></tr>
      <tr><td>소계</td><td>5,300,000</td><td>53.65%</td><td>4,600,000</td><td>46.45%</td></tr>
      <tr><td>합계</td><td>8,690,000</td><td>60.04%</td><td>5,786,500</td><td>39.96%</td></tr>
    </table>"""
    assert scraper._parse_circulating(_soup(html)) == 5_786_500


def test_parse_circulating_accepts_seongmyeong_label():
    # 재상장·이전상장 종목은 '주주명' 대신 '성명' 라벨을 쓴다 → 둘 다 허용해야 한다.
    html = """
    <table>
      <tr><th>성명</th><th>공모전</th><th>지분율</th><th>공모후 유통가능물량</th><th>지분율</th></tr>
      <tr><td>합계</td><td>3,000,000</td><td>30.00%</td><td>7,000,000</td><td>70.00%</td></tr>
    </table>"""
    assert scraper._parse_circulating(_soup(html)) == 7_000_000


def test_parse_circulating_spaced_label():
    # 함정(레메디): 38이 라벨을 '성 명'·'구 분'처럼 공백을 넣어 표기 → 공백 무시 매칭 필요.
    # 데이터행도 다열(공모전/공모후 보유/매각제한/유통가능). 합계행에서 유통가능주식수 추출.
    html = """
    <table>
      <tr><td>구 분</td><td>성 명</td><td>회사와의 관계</td><td>공모전 보유주식</td><td>공모후</td><td>매각</td></tr>
      <tr><td>관계</td><td>보유주식(A)</td><td>매각제한물량(B)</td><td>유통가능물량(A-B)</td><td>제한 기간</td></tr>
      <tr><td>최대주주등</td><td>이레나</td><td>최대주주</td><td>2,805,440</td><td>43.91%</td>
          <td>2,805,440</td><td>36.79%</td><td>2,805,440</td><td>36.79%</td><td>0</td><td>0.00%</td><td>3년</td></tr>
      <tr><td>합계</td><td>6,389,791</td><td>100.00%</td><td>7,625,791</td><td>100.00%</td>
          <td>4,496,631</td><td>58.96%</td><td>3,129,160</td><td>41.03%</td><td>-</td></tr>
    </table>"""
    assert scraper._parse_circulating(_soup(html)) == 3_129_160


def test_parse_circulating_none_when_no_table():
    assert scraper._parse_circulating(_soup("<table><tr><td>무관</td></tr></table>")) is None


def test_circ_pair_in_cells_direct():
    cells = ["합계", "8,690,000", "60.04%", "5,786,500", "39.96%"]
    assert scraper._circ_pair_in_cells(cells) == 5_786_500
    # 비율 합이 100에서 벗어나면 매칭 안 함
    assert scraper._circ_pair_in_cells(["x", "1,000,000", "10%", "2,000,000", "20%"]) is None


# ===========================================================================
# 기관 총 신청수량 — _parse_inst_demand
# ===========================================================================
def test_parse_inst_demand_ignores_wrapper_row():
    # 함정: 페이지 전체가 담긴 거대 wrapper 행(셀 1개)에 앞서 나오는 확약수량
    # 180,918,700(≥1억)이 총신청수량으로 오인됐다. → 단순경쟁률(…:1) 있는 '짧은 행'만 인정.
    html = """
    <table>
      <tr><td>참여건수 2,252 신청주식수 1,502,187,765 3개월 확약 180,918,700 단순경쟁률 1,294.99:1</td></tr>
      <tr><td>2,252</td><td>1,502,187,765</td><td>1,294.99:1</td></tr>
    </table>"""
    assert scraper._parse_inst_demand(_soup(html)) == 1_502_187_765


def test_parse_inst_demand_none_without_ratio_row():
    html = "<table><tr><td>참여건수</td><td>1,502,187,765</td></tr></table>"
    assert scraper._parse_inst_demand(_soup(html)) is None


# ===========================================================================
# 의무보유확약 합계 — _sum_lockup_quantity
# ===========================================================================
def test_sum_lockup_quantity_excludes_period_numbers_and_total():
    # 함정: 'X개월 확약' 셀이 parse_number 로 6/3/1 처럼 작은 수가 된다.
    # → ≥10,000 가드로 기간 숫자를 배제하고 수량만 합산. '합계' 행 제외.
    html = """
    <table>
      <tr><th>확약기간</th><th>신청수량</th></tr>
      <tr><td>15일 확약</td><td>10,000,000</td></tr>
      <tr><td>1개월 확약</td><td>20,000,000</td></tr>
      <tr><td>3개월 확약</td><td>30,000,000</td></tr>
      <tr><td>6개월 확약</td><td>40,000,000</td></tr>
      <tr><td>합계</td><td>100,000,000</td></tr>
    </table>"""
    assert scraper._sum_lockup_quantity(_soup(html)) == 100_000_000


def test_sum_lockup_quantity_skips_shareholder_table():
    # '주주명' 포함 표(주주현황)는 확약 기간이 섞여도 제외해야 한다.
    html = """
    <table>
      <tr><th>주주명</th><th>신청수량</th></tr>
      <tr><td>3개월 확약</td><td>30,000,000</td></tr>
    </table>"""
    assert scraper._sum_lockup_quantity(_soup(html)) is None


# ===========================================================================
# 배정물량 / 공모가 밴드 — _parse_alloc_max / _parse_band
# ===========================================================================
def test_parse_alloc_max_picks_range_max():
    assert scraper._parse_alloc_max("1,080,000~1,160,000 주") == 1_160_000
    assert scraper._parse_alloc_max("1,160,000 주") == 1_160_000
    assert scraper._parse_alloc_max("미정") is None


def test_parse_band_high_low():
    assert scraper._parse_band("19,000 ~ 21,500 원") == (21_500, 19_000)
    assert scraper._parse_band("없음") == (None, None)


def test_is_listed():
    from datetime import date
    today = date(2026, 7, 1)
    assert scraper._is_listed("2026-06-30", today) is True    # 어제 상장 → 이미 상장
    assert scraper._is_listed("2026-07-01", today) is False   # 오늘 상장 → '이미'는 아님
    assert scraper._is_listed("2026-07-13", today) is False   # 미래 상장
    assert scraper._is_listed(None, today) is False           # 상장일 미상 → 보수적 유지
    assert scraper._is_listed("미정", today) is False          # 파싱 실패 → 유지


# ===========================================================================
# 장외 호가 — get_otc_price / _reject_otc_outliers / _extract_price_from_row
# ===========================================================================
def test_get_otc_price_both_sides_average():
    # 매도·매수 모두 존재(이상치 없음) → 통합 평균
    otc = scraper.get_otc_price("X", sell_prices=[55000, 57000, 58000],
                                buy_prices=[54000, 56000, 59000])
    assert otc == 56500.0


def test_get_otc_price_one_side_returns_none():
    # 매수호가만 있으면 장외 '없음'(-2 대상). 네트워크 호출 없이 None.
    assert scraper.get_otc_price("X", sell_prices=[], buy_prices=[54000, 56000]) is None


def test_get_otc_price_rejects_outliers_then_average():
    # 중앙값 ±40% 밖(10만 매도·2만 매수)을 제거한 뒤 평균
    otc = scraper.get_otc_price("X", sell_prices=[55000, 57000, 100000],
                                buy_prices=[54000, 56000, 20000])
    assert otc == 55500.0


def test_get_otc_quote_avg_and_min():
    # 평균·최소 동시 산출 (레메디 호가: 팝니다 46000×4·43000, 삽니다 41000×5)
    q = scraper.get_otc_quote("X", confirmed_price=20700,
                              sell_prices=[46000, 46000, 46000, 46000, 43000],
                              buy_prices=[41000, 41000, 41000, 41000, 41000])
    assert q["min"] == 41000.0
    assert round(q["avg"]) == 43200          # (46000*4+43000+41000*5)/10


def test_get_otc_quote_one_side_none():
    assert scraper.get_otc_quote("X", sell_prices=[], buy_prices=[41000, 42000]) == {"avg": None, "min": None}


def test_extract_price_from_row_picks_price_not_small_number():
    row = _soup("<table><tr><td>1</td><td>55,000</td><td>수량 10</td></tr></table>").find("tr")
    assert scraper._extract_price_from_row(row) == 55_000


# ===========================================================================
# DART 수요예측 표 — _parse_demand_table (inst_total 경로만; 구조 명확)
# ===========================================================================
# ⚠️ 확약/배정 추출은 실제 DART 문서 구조에 민감하므로, 신뢰성 있는 회귀 테스트를
#    위해서는 실제 캡처 HTM 픽스처가 필요하다(추후 보강 권장). 여기서는 구조가 명확한
#    '참여건수+신청주식수 → 총신청수량(≥1억)' 경로와 폴백(None)만 고정한다.
def test_dart_demand_extracts_inst_total():
    html = """
    <table>
      <tr><th>참여건수 (단위:건)</th><th>신청주식수 (단위:주)</th></tr>
      <tr><td>2,329</td><td>1,444,988,385</td></tr>
    </table>"""
    r = dart._parse_demand_table(_soup(html))
    assert r is not None and r["inst_total_demand"] == 1_444_988_385


def test_dart_demand_returns_none_without_inst_total():
    # 핵심 수치(총신청수량) 미확보 → None(38 폴백 트리거)
    assert dart._parse_demand_table(_soup("<table><tr><td>무관</td></tr></table>")) is None
