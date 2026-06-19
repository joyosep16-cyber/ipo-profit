"""핵심 산식 + 스코어링 + 점수별 청약 추천 등급 + DART 교차검증 병합.

🚨 산식은 가이드 규칙대로 '원본 수량'에서 직접 계산한다(표시 % 재사용 금지).
의무보유확약 비율 분모 = 기관 총 신청수량 (총공모주식수 절대 아님!).
원본 수량이 없을 때만 build_metrics 에서 표시 % 폴백을 사용한다.
"""
from typing import Optional

from analyzer import config


# ===========================================================================
# 4대 핵심 산식 (순수 함수)
# ===========================================================================
def lockup_ratio(lockup_qty: float, inst_total_demand: float) -> float:
    """[의무보유확약 비율(%)] = 확약 신청수량 합계 / 기관 총 신청수량 * 100"""
    if not inst_total_demand:
        return 0.0
    return lockup_qty / inst_total_demand * 100.0


def inst_competition(inst_total_demand: float, inst_allocation: float) -> float:
    """[기관 경쟁률] = 기관 총 신청수량 / 기관 배정물량"""
    if not inst_allocation:
        return 0.0
    return inst_total_demand / inst_allocation


def circulating_value(circulating_shares: float, confirmed_price: float) -> float:
    """[공모후 유통가능물량(금액, 원)] = 유통가능주식수 * 확정공모가"""
    return (circulating_shares or 0) * (confirmed_price or 0)


def otc_premium(otc_price: Optional[float], confirmed_price: float) -> float:
    """[장외 괴리율(%)] = (장외유추가격 - 확정공모가) / 확정공모가 * 100
    장외가가 없으면(None) 괴리율 0%로 처리."""
    if otc_price is None or not confirmed_price:
        return 0.0
    return (otc_price - confirmed_price) / confirmed_price * 100.0


def is_spac_or_reit(name: str) -> bool:
    """종목명이 스팩(SPAC) 또는 리츠(REIT)인지 판정.

    스팩·리츠는 일반 공모주와 성격이 달라(장외 거래 없음, 점수 산정 부적합)
    별도 예외 처리 대상이다. 영문 'SPAC'은 대소문자 무시.
    """
    if not name:
        return False
    upper = name.upper()
    return any(kw in name for kw in ("스팩", "호스팩", "리츠")) or "SPAC" in upper


def calc_deposit(confirmed_price: float, min_qty: int, deposit_rate: float = 0.5) -> int:
    """[필요 최소 증거금(원)] = 확정공모가 × 최소청약수량 × 증거금률(50%)."""
    return int(round(confirmed_price * min_qty * deposit_rate))


def build_deposit_map(confirmed_price: float, min_qty_map: dict) -> dict:
    """주관사별 최소 증거금 계산.

    min_qty_map 형식: {"NH투자증권": {"min_qty": 10, "estimated": True}, ...}
    반환: {"NH투자증권": {"min_qty": 10, "estimated": True, "deposit": 107500}, ...}
    """
    result = {}
    for name, info in min_qty_map.items():
        deposit = calc_deposit(confirmed_price, info["min_qty"])
        result[name] = {**info, "deposit": deposit}
    return result


# ===========================================================================
# DART 교차검증 병합 (Source B 우선, 실패 시 38 폴백)
# ===========================================================================
def merge_sources(scraper_data: dict, dart_data: Optional[dict]) -> dict:
    """DART 원본 수량을 우선 적용하고 데이터 신뢰도(data_quality)를 태깅.

    - DART_API_KEY 미설정: data_quality 없이 원본 반환 (기존 동작 유지)
    - DART 실패(None): '🔴 38 폴백(추정치)'
    - DART 성공 + 10% 이내 일치: '🟢 일치'
    - DART 성공 + 불일치: '🟡 DART 보정됨' (DART 수치 우선 적용)

    🚨 산식 분모 확인: DART inst_total_demand → build_metrics 에서 raw_verified=True 로 연산.
    """
    # DART 키 없음 → 교차검증 미수행, data_quality 미설정
    if not config.DART_API_KEY:
        return dict(scraper_data)

    if dart_data is None:
        return {**scraper_data, "data_quality": "🔴 38 폴백(추정치)"}

    merged = dict(scraper_data)

    # DART 수치로 덮어쓰기 (원본 수량 확보됨으로 마킹)
    merged["inst_total_demand"] = dart_data["inst_total_demand"]
    merged["lockup_qty"] = dart_data["lockup_qty"]
    if dart_data.get("inst_allocation"):
        merged["inst_allocation"] = dart_data["inst_allocation"]
    merged["raw_verified"] = True   # DART 원본 수량 확보 → 산식 직접 계산 경로 활성화
    merged["dart_rcept_no"] = dart_data.get("rcept_no", "")

    # 두 소스 수치 비교 (10% 오차 허용)
    s_total = scraper_data.get("inst_total_demand")
    d_total = dart_data["inst_total_demand"]
    if s_total and d_total:
        diff_ratio = abs(s_total - d_total) / d_total
        merged["data_quality"] = "🟢 일치" if diff_ratio < 0.10 else "🟡 DART 보정됨"
    else:
        # 38 수치 자체가 없었던 경우
        merged["data_quality"] = "🟡 DART 보정됨"

    return merged


# ===========================================================================
# 지표 묶음 생성 (원본 우선, 실패 시 폴백)
# ===========================================================================
def build_metrics(detail: dict, otc_price: Optional[float],
                  skip_otc: bool = False) -> dict:
    """스크래퍼 상세 dict + 장외가 → 평가용 지표 dict.

    raw_verified=True 면 산식으로 직접 계산, False 면 표시 % 폴백을 사용.
    skip_otc=True (스팩/리츠) 면 장외 괴리율을 계산하지 않고 None 으로 둔다.
    """
    confirmed_price = detail.get("confirmed_price") or 0

    if detail.get("raw_verified"):
        comp = inst_competition(detail["inst_total_demand"], detail["inst_allocation"])
        lockup = lockup_ratio(detail["lockup_qty"], detail["inst_total_demand"])
        circ_value = circulating_value(detail["circulating_shares"], confirmed_price)
    else:
        # 폴백: 사이트 표시 값(없으면 0)
        comp = detail.get("fallback_competition") or 0.0
        lockup = detail.get("fallback_lockup") or 0.0
        circ_value = circulating_value(detail.get("circulating_shares") or 0, confirmed_price)

    # 스팩/리츠는 장외 거래가 없으므로 괴리율 미산정(None)
    # 일반 종목인데 otc_price 가 None 이면 '장외 시세 없음'(매도호가 없음 등) → 괴리율 None
    if skip_otc or otc_price is None:
        premium = None
    else:
        premium = otc_premium(otc_price, confirmed_price)
    # 장외 시세 없음: 스팩/리츠가 아닌데 장외가가 없는 경우(점수 -2 대상)
    otc_missing = (not skip_otc) and (otc_price is None)

    # 주관사별 증거금 계산 (min_qty_map이 없으면 빈 dict)
    min_qty_map = detail.get("min_qty_map") or {}
    deposit_map = build_deposit_map(confirmed_price, min_qty_map)

    return {
        "inst_competition": comp,
        "lockup_ratio": lockup,
        "circulating_value": circ_value,             # 원 단위
        "circulating_eok": circ_value / config.EOK,  # 억 단위 (억=1억=100,000,000원)
        "otc_premium": premium,                      # 스팩/리츠·장외없음 → None (N/A)
        "otc_price": None if skip_otc else otc_price,
        "otc_missing": otc_missing,                  # 일반 종목인데 장외 시세 없음
        "confirmed_price": confirmed_price,
        "raw_verified": detail.get("raw_verified", False),
        "deposit_map": deposit_map,  # {"NH투자증권": {"min_qty":10,"estimated":True,"deposit":107500}}
        "otc_skipped": skip_otc,
    }


# ===========================================================================
# 항목별 점수 헬퍼
# ===========================================================================
def _score_ge(value: float, table: list[tuple]) -> int:
    """value >= 임계값 인 첫 항목의 점수(내림차순 테이블)."""
    for threshold, score in table:
        if value >= threshold:
            return score
    return 0


def _score_le(value: float, table: list[tuple]) -> int:
    """value <= 임계값 인 첫 항목의 점수(오름차순 테이블)."""
    for threshold, score in table:
        if value <= threshold:
            return score
    return 0


def _score_otc(premium, is_simultaneous: bool = False,
               otc_missing: bool = False) -> int:
    """장외가격 칸 단일 점수(합산 아님). 우선순위로 하나만 적용한다.

      1) 동시상장(같은 상장일 종목 존재) → -2  (괴리율과 무관하게 무조건)
      2) 장외 시세 없음(매도호가 없음)    → -2
      3) 괴리율 기반: +160%↑=6, +100%↑=3, +50%↑=0, +50%미만=-3

    분석가 채점표에서 '동시상장'은 장외가격 칸의 한 값이므로, 괴리율 점수에
    더하지 않고 대체한다.
    """
    if is_simultaneous:
        return config.SCORE_SIMULTANEOUS_PENALTY   # -2 (최우선)
    if otc_missing or premium is None:
        return config.SCORE_OTC_MISSING            # -2 (장외 없음)
    for threshold, score in config.SCORE_OTC_PREMIUM:  # [(160,6),(100,3),(50,0)]
        if premium >= threshold:
            return score
    return config.SCORE_OTC_PENALTY  # -3


# ===========================================================================
# 종합 스코어링
# ===========================================================================
def evaluate_ipo_score(metrics: dict, is_simultaneous: bool = False,
                       is_spac_reit: bool = False) -> dict:
    """지표 → 항목별 점수 + 총점 + 추천 등급 dict.

    is_simultaneous: 같은 상장일 종목이 배치 내 2개 이상이면 True (-2점).
    is_spac_reit: 스팩/리츠면 점수 산정을 건너뛰고 안내 메시지를 담은 dict 반환.
    """
    # ── 스팩/리츠 예외: 점수 산정 제외 ───────────────────────────────
    if is_spac_reit:
        return {
            "scores": None,
            "total": None,
            "is_simultaneous": is_simultaneous,
            "is_spac_reit": True,
            "grade": "평가 제외 (SPAC/리츠)",
            "emoji": "ℹ️",
            "verdict": "점수 산정 대상 아님",
            "action": "[SPAC/리츠 종목] 기본 지표(경쟁률, 확약비율)만 참고 바람",
            "expected_return": "스팩/리츠는 일반 공모주 수익 모델과 다름",
            "color": 0x3498DB,   # 파란색 — 정보성
            "notice": "[SPAC/리츠 종목] 기본 지표(경쟁률, 확약비율)만 참고 바람",
        }

    s_comp = _score_ge(metrics["inst_competition"], config.SCORE_INST_COMPETITION)
    s_lockup = _score_ge(metrics["lockup_ratio"], config.SCORE_LOCKUP)
    s_circ = _score_le(metrics["circulating_eok"], config.SCORE_CIRCULATING_EOK)
    # 장외가격 칸 = 단일 점수(동시상장 > 장외없음 > 괴리율). 별도 합산 항목 없음.
    s_otc = _score_otc(metrics["otc_premium"], is_simultaneous=is_simultaneous,
                       otc_missing=metrics.get("otc_missing", False))

    total = s_comp + s_lockup + s_circ + s_otc
    recommendation = grade_recommendation(total)

    return {
        "scores": {
            "inst_competition": s_comp,
            "lockup_ratio": s_lockup,
            "circulating": s_circ,
            "otc_premium": s_otc,   # 동시상장/장외없음/괴리율 중 하나가 반영된 단일 점수
        },
        "total": total,
        "is_simultaneous": is_simultaneous,
        **recommendation,  # grade, action, expected_return, color, emoji
    }


# ===========================================================================
# 점수별 청약 추천 등급 (가이드 9장 기준)
#   0~5  : 손실위험   → 청약 비권장
#   5~10 : 손실가능   → 신중
#   10~15: 50% 수익   → 청약 고려
#   15~20: 100% 수익  → 강력 청약
#   20+  : 160%+ 수익 → 최우선 청약
# ===========================================================================
def grade_recommendation(total: int) -> dict:
    """총점 → 등급/행동지침/예상수익률. 알림 메시지를 깔끔하게 구성하기 위한 텍스트 포함."""
    if total >= 20:
        return {
            "grade": "최우선 청약",
            "emoji": "🟢🔥",
            "action": "전 계좌 비례+균등 적극 청약 권장",
            "expected_return": "예상 수익률 160% 이상",
            "color": 0x00FF00,
            "verdict": "청약하세요 (최우선)",
        }
    if total >= 15:
        return {
            "grade": "강력 청약",
            "emoji": "🟢",
            "action": "균등 배정 + 여력 시 비례 청약 권장",
            "expected_return": "예상 수익률 100~160% 구간",
            "color": 0x00FF00,
            "verdict": "청약하세요",
        }
    if total >= 10:
        return {
            "grade": "청약 고려",
            "emoji": "🟡",
            "action": "균등 배정 위주로 소액 청약 고려",
            "expected_return": "예상 수익률 50% 내외",
            "color": 0xFFCC00,
            "verdict": "선택적 청약",
        }
    if total >= 5:
        return {
            "grade": "신중",
            "emoji": "🟠",
            "action": "손실 가능 구간 — 청약 신중히 판단",
            "expected_return": "수익/손실 혼재 (손실 가능)",
            "color": 0xFF8800,
            "verdict": "청약 신중",
        }
    return {
        "grade": "청약 비권장",
        "emoji": "🔴",
        "action": "손실 위험 구간 — 청약 비권장",
        "expected_return": "손실 위험",
        "color": 0xFF0000,
        "verdict": "청약하지 마세요",
    }
