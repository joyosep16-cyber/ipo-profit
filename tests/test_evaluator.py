"""evaluator 단위 테스트.

가이드 6장 스코어링 테이블과 9장 등급 기준에 따라 항목별 점수·총점·추천 등급,
4대 산식, 장외 호가 이상치 제거(scraper) 경계값을 검증한다.

실행: pytest -q   또는   python -m pytest tests/
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from analyzer import evaluator  # noqa: E402


# ---------------------------------------------------------------------------
# 핵심 산식
# ---------------------------------------------------------------------------
def test_lockup_ratio():
    # 확약 200, 총신청 1000 → 20%
    assert evaluator.lockup_ratio(200, 1000) == 20.0
    assert evaluator.lockup_ratio(0, 0) == 0.0  # 분모 0 방어


def test_inst_competition():
    # 총신청 480000, 배정 1000 → 480:1
    assert evaluator.inst_competition(480000, 1000) == 480.0
    assert evaluator.inst_competition(100, 0) == 0.0  # 분모 0 방어


def test_circulating_value():
    # 유통 100만주 * 5만원 = 500억
    assert evaluator.circulating_value(1_000_000, 50_000) == 50_000_000_000


def test_otc_premium():
    # 장외 13만, 공모 5만 → +160%
    assert round(evaluator.otc_premium(130_000, 50_000), 1) == 160.0
    assert evaluator.otc_premium(None, 50_000) == 0.0  # 장외 없음 → 0%


def test_circulating_eok_from_shares():
    # 유통가능금액(억) = 주식수 × 확정공모가 / 1억
    assert evaluator.circulating_eok_from_shares(1_000_000, 30_000) == 300.0
    assert evaluator.circulating_eok_from_shares(None, 30_000) == 0.0      # 주식수 없음
    assert evaluator.circulating_eok_from_shares(1_000_000, None) == 0.0   # 공모가 없음


def test_circulating_missing_rescored_by_shares():
    # 유통 데이터 없는 종목(0점)을 주식수×공모가로 보정하면 정상 채점된다.
    metrics = {
        "inst_competition": 550.0, "lockup_ratio": 35.0, "circulating_eok": 0.0,
        "circulating_missing": True, "otc_premium": 200.0, "raw_verified": True,
    }
    assert evaluator.evaluate_ipo_score(metrics)["scores"]["circulating"] == 0
    eok = evaluator.circulating_eok_from_shares(1_000_000, 30_000)   # 300억
    assert eok == 300.0
    m2 = {**metrics, "circulating_eok": eok, "circulating_missing": False}
    # 300억 → SCORE_CIRCULATING_EOK 에서 <=500 구간 = 6점
    assert evaluator.evaluate_ipo_score(m2)["scores"]["circulating"] == 6


# ---------------------------------------------------------------------------
# 항목별 점수 경계값
# ---------------------------------------------------------------------------
def _score(comp, lockup, circ_eok, premium, simul=False):
    metrics = {
        "inst_competition": comp,
        "lockup_ratio": lockup,
        "circulating_eok": circ_eok,
        "otc_premium": premium,
        "raw_verified": True,
    }
    return evaluator.evaluate_ipo_score(metrics, simul)


def test_score_table_high():
    # 경쟁률 500↑(5) + 확약 30↑(10) + 유통 200억↓(10) + 괴리 160↑(6) = 31점
    r = _score(550, 35, 150, 200)
    assert r["scores"] == {"inst_competition": 5, "lockup_ratio": 10,
                           "circulating": 10, "otc_premium": 6}
    assert r["total"] == 31


def test_score_boundaries():
    # 경계값: 경쟁률 450(4), 확약 20(8), 유통 500억(6), 괴리 100(3)
    r = _score(450, 20, 500, 100)
    assert r["scores"]["inst_competition"] == 4
    assert r["scores"]["lockup_ratio"] == 8
    assert r["scores"]["circulating"] == 6
    assert r["scores"]["otc_premium"] == 3
    assert r["total"] == 21


def test_otc_penalty():
    # 괴리율 +50% 미만 → -3 감점
    r = _score(300, 5, 3000, 10)
    assert r["scores"]["otc_premium"] == -3


def test_simultaneous_overrides_otc():
    # 동시상장이면 괴리율(+160%→6)과 무관하게 장외 칸 = -2 (합산이 아니라 대체)
    r = _score(550, 35, 150, 200, simul=True)
    assert r["scores"]["otc_premium"] == -2
    assert r["total"] == 5 + 10 + 10 - 2   # 23
    assert r["is_simultaneous"] is True


def test_circulating_missing_no_bonus():
    # 유통가능물량 데이터 없음(circulating_missing) → 0억이라도 만점(10) 주지 않고 0점
    metrics = {
        "inst_competition": 550.0, "lockup_ratio": 35.0, "circulating_eok": 0.0,
        "circulating_missing": True, "otc_premium": 200.0, "raw_verified": True,
    }
    r = evaluator.evaluate_ipo_score(metrics)
    assert r["scores"]["circulating"] == 0
    # 수동 입력으로 보정하면 정상 채점
    m2 = {**metrics, "circulating_eok": 150.0, "circulating_missing": False}
    assert evaluator.evaluate_ipo_score(m2)["scores"]["circulating"] == 10


def test_otc_missing_penalty():
    # 장외 시세 없음(매도/매수호가 중 하나라도 없음) → 장외 칸 -2
    metrics = {
        "inst_competition": 550.0, "lockup_ratio": 35.0, "circulating_eok": 150.0,
        "otc_premium": None, "otc_missing": True, "raw_verified": True,
    }
    r = evaluator.evaluate_ipo_score(metrics)
    assert r["scores"]["otc_premium"] == -2
    assert r["total"] == 5 + 10 + 10 - 2   # 23


# ---------------------------------------------------------------------------
# 점수별 추천 등급 (9장 기준)
# ---------------------------------------------------------------------------
def test_grade_recommendation():
    assert evaluator.grade_recommendation(25)["verdict"] == "청약하세요 (최우선)"
    assert evaluator.grade_recommendation(16)["verdict"] == "청약하세요"
    assert evaluator.grade_recommendation(12)["verdict"] == "선택적 청약"
    assert evaluator.grade_recommendation(7)["verdict"] == "청약 신중"
    assert evaluator.grade_recommendation(3)["verdict"] == "청약하지 마세요"


# ---------------------------------------------------------------------------
# 장외 호가 이상치 제거 (scraper._reject_otc_outliers)
# ---------------------------------------------------------------------------
def test_reject_otc_outliers():
    from analyzer.scraper import _reject_otc_outliers

    # 대부분 5~6만인데 10만(터무니없는 매도)·2만(헐값 매수) 섞임 → 둘 다 제외
    prices = [55000, 57000, 58000, 60000, 100000, 20000]
    kept = sorted(_reject_otc_outliers(prices))
    assert kept == [55000, 57000, 58000, 60000]
    assert sum(kept) / len(kept) == 57500.0


def test_reject_otc_outliers_small_sample():
    from analyzer.scraper import _reject_otc_outliers

    # 3개 미만이면 중앙값 신뢰 불가 → 원본 유지(0·None 만 정리)
    assert _reject_otc_outliers([50000, 90000]) == [50000, 90000]
    assert _reject_otc_outliers([50000, None, 0, 60000]) == [50000, 60000]
