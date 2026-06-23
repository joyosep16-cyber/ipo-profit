"""normalizer 및 merge_sources 단위 테스트."""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from analyzer.normalizer import is_same_company, normalize  # noqa: E402
from analyzer import evaluator  # noqa: E402


# ---------------------------------------------------------------------------
# 기업명 정규화
# ---------------------------------------------------------------------------
def test_normalize_removes_prefix():
    assert normalize("(주)피스피스스튜디오") == "피스피스스튜디오"
    assert normalize("㈜피스피스스튜디오") == "피스피스스튜디오"
    assert normalize("주식회사피스피스스튜디오") == "피스피스스튜디오"


def test_normalize_removes_whitespace_special():
    assert normalize("피스 피스 스튜디오") == "피스피스스튜디오"
    assert normalize("피스피스(스튜디오)") == "피스피스스튜디오"


def test_normalize_lowercase():
    assert normalize("KakaoBank") == "kakaobank"
    assert normalize("(주)카카오뱅크") == "카카오뱅크"


def test_normalize_empty():
    assert normalize("") == ""
    assert normalize("  ") == ""


def test_is_same_company_exact():
    assert is_same_company("피스피스스튜디오", "피스피스스튜디오") is True


def test_is_same_company_prefix_variant():
    assert is_same_company("(주)피스피스스튜디오", "피스피스스튜디오") is True
    assert is_same_company("㈜씨엠티엑스", "씨엠티엑스") is True


def test_is_same_company_different():
    assert is_same_company("카카오뱅크", "카카오페이") is False


def test_is_same_company_empty():
    assert is_same_company("", "카카오뱅크") is False


# ---------------------------------------------------------------------------
# merge_sources 교차검증 병합
# ---------------------------------------------------------------------------
_SCRAPER_BASE = {
    "name": "테스트종목",
    "no": "9999",
    "inst_total_demand": 1_000_000_000,
    "inst_allocation": 2_000_000,
    "lockup_qty": 50_000_000,
    "circulating_shares": 5_000_000,
    "confirmed_price": 30_000,
    "raw_verified": True,
    "fallback_competition": None,
    "fallback_lockup": None,
}

_DART_OK = {
    "inst_total_demand": 1_010_000_000,   # 1% 차이 → 일치
    "lockup_qty": 51_000_000,
    "inst_allocation": 2_000_000,
    "corp_code": "00000001",
    "rcept_no": "20260101000001",
    "source": "DART",
}

_DART_MISMATCH = {
    "inst_total_demand": 1_500_000_000,   # 50% 차이 → 불일치
    "lockup_qty": 75_000_000,
    "inst_allocation": 2_000_000,
    "corp_code": "00000001",
    "rcept_no": "20260101000002",
    "source": "DART",
}


def test_merge_no_dart_key(monkeypatch):
    """DART 키 없으면 data_quality 미설정 (env 미설정 = 런타임 키 없음)."""
    monkeypatch.delenv("DART_API_KEY", raising=False)
    result = evaluator.merge_sources(_SCRAPER_BASE, None)
    assert "data_quality" not in result


def test_merge_dart_none(monkeypatch):
    """DART 실패 → 38 폴백."""
    monkeypatch.setenv("DART_API_KEY", "dummy_key")
    result = evaluator.merge_sources(_SCRAPER_BASE, None)
    assert result["data_quality"] == "🔴 38 폴백(추정치)"


def test_merge_dart_match(monkeypatch):
    """DART 수치 10% 이내 일치 → 🟢."""
    monkeypatch.setenv("DART_API_KEY", "dummy_key")
    result = evaluator.merge_sources(_SCRAPER_BASE, _DART_OK)
    assert result["data_quality"] == "🟢 일치"
    assert result["inst_total_demand"] == _DART_OK["inst_total_demand"]
    assert result["raw_verified"] is True


def test_merge_dart_mismatch(monkeypatch):
    """DART 수치 10% 초과 불일치 → 🟡, DART 값 적용."""
    monkeypatch.setenv("DART_API_KEY", "dummy_key")
    result = evaluator.merge_sources(_SCRAPER_BASE, _DART_MISMATCH)
    assert result["data_quality"] == "🟡 DART 보정됨"
    assert result["inst_total_demand"] == _DART_MISMATCH["inst_total_demand"]


def test_merge_dart_key_runtime_injection(monkeypatch):
    """회귀 방지: import 시점 동결 상수가 아니라 런타임 env 를 봐야 한다.
    config.DART_API_KEY(동결 빈값)와 무관하게 env 가 있으면 교차검증 수행."""
    from analyzer import config
    monkeypatch.setattr(config, "DART_API_KEY", "")     # import 시점 동결값(빈값) 모사
    monkeypatch.setenv("DART_API_KEY", "late_injected")  # 런타임 주입
    result = evaluator.merge_sources(_SCRAPER_BASE, _DART_OK)
    assert result["data_quality"] == "🟢 일치"           # 동결 상수였다면 미설정으로 스킵됨
