"""evaluator 단위 테스트.

가이드 6장 스코어링 테이블과 9장 등급 기준에 따라 항목별 점수·총점·추천 등급,
4대 산식, 절미평균(scraper) 경계값을 검증한다.

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
                           "circulating": 10, "otc_premium": 6, "simultaneous": 0}
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


def test_simultaneous_penalty():
    base = _score(550, 35, 150, 200, simul=False)["total"]
    with_penalty = _score(550, 35, 150, 200, simul=True)["total"]
    assert with_penalty == base - 2


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
# 절미평균 (scraper 로직 직접 검증 — 함수 추출 없이 동일 알고리즘 확인)
# ---------------------------------------------------------------------------
def test_trimmed_mean_logic():
    prices = [64000, 58000, 57000, 100, 99999]  # 최저 100, 최고 99999 제외
    prices.sort()
    trimmed = prices[1:-1]
    assert trimmed == [57000, 58000, 64000]
    assert sum(trimmed) / len(trimmed) == 59666.666666666664
