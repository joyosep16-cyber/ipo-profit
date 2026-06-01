"""스팩/리츠 예외 처리 단위 테스트."""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from analyzer import evaluator  # noqa: E402


# ---------------------------------------------------------------------------
# 스팩/리츠 판정
# ---------------------------------------------------------------------------
def test_is_spac_korean():
    assert evaluator.is_spac_or_reit("한국스팩16호") is True
    assert evaluator.is_spac_or_reit("메리츠스팩2호") is True
    assert evaluator.is_spac_or_reit("NH스팩33호") is True


def test_is_reit():
    assert evaluator.is_spac_or_reit("SK리츠") is True
    assert evaluator.is_spac_or_reit("맥쿼리인프라리츠") is True


def test_is_spac_english():
    assert evaluator.is_spac_or_reit("ABC SPAC Corp") is True
    assert evaluator.is_spac_or_reit("xyz spac") is True   # 소문자도 인식


def test_not_spac():
    assert evaluator.is_spac_or_reit("피스피스스튜디오") is False
    assert evaluator.is_spac_or_reit("씨엠티엑스") is False
    assert evaluator.is_spac_or_reit("") is False


# ---------------------------------------------------------------------------
# 스팩/리츠 점수 산정 제외
# ---------------------------------------------------------------------------
_SPAC_METRICS = {
    "inst_competition": 500.0,
    "lockup_ratio": 5.0,
    "circulating_eok": 100.0,
    "otc_premium": None,       # 장외 스킵
    "raw_verified": True,
    "otc_skipped": True,
}


def test_spac_score_excluded():
    result = evaluator.evaluate_ipo_score(_SPAC_METRICS, is_spac_reit=True)
    assert result["total"] is None             # 점수 산정 제외
    assert result["is_spac_reit"] is True
    assert "SPAC/리츠" in result["grade"]
    assert "기본 지표" in result["notice"]


def test_spac_build_metrics_skips_otc():
    detail = {
        "confirmed_price": 2000,
        "raw_verified": True,
        "inst_total_demand": 500_000_000,
        "inst_allocation": 1_000_000,
        "lockup_qty": 25_000_000,
        "circulating_shares": 5_000_000,
        "min_qty_map": {},
    }
    metrics = evaluator.build_metrics(detail, otc_price=99999, skip_otc=True)
    assert metrics["otc_premium"] is None      # 장외가가 있어도 스킵 시 None
    assert metrics["otc_price"] is None
    assert metrics["otc_skipped"] is True


def test_normal_stock_still_scored():
    """일반 종목은 기존대로 점수 산정."""
    metrics = {
        "inst_competition": 550.0, "lockup_ratio": 35.0,
        "circulating_eok": 150.0, "otc_premium": 200.0, "raw_verified": True,
    }
    result = evaluator.evaluate_ipo_score(metrics, is_spac_reit=False)
    assert result["total"] == 31
    assert result.get("is_spac_reit") is None or result.get("is_spac_reit") is False
