"""분석 파이프라인 오케스트레이션 (페이지·스케줄러 공용).

흐름: fetch_detail → DART 교차검증 → merge → (스팩/리츠 아니면) 장외가 → 산식 → 스코어링
페이지(pages/analysis.py)와 스케줄러(utils/scheduler.py)가 동일 로직을 재사용한다.
"""
from typing import Optional

from analyzer import dart, evaluator, scraper
from analyzer.net import logger
from analyzer.normalizer import is_same_company


def analyze_by_no(no: str, is_simultaneous: bool = False) -> Optional[dict]:
    """고유번호(no)로 1종목 분석. 결과 번들 dict 반환, 실패 시 None.

    is_simultaneous: 같은 상장일에 동시상장하는 종목이 있으면 True (장외 칸 -2).
      38에 종목별 상장일 목록이 없어 자동 판정이 어렵기에, 사용자가 수동 지정한다.
      (분석 페이지의 '동시상장' 체크박스에서 점수만 재계산하므로 기본값 False)

    반환: {"merged", "metrics", "result", "is_spac", "name"}
      - merged: scraper.fetch_detail + merge_sources (data_quality 포함)
      - metrics: evaluator.build_metrics
      - result: evaluator.evaluate_ipo_score (스팩이면 total=None)
    """
    detail = scraper.fetch_detail(no)
    if not detail:
        logger.info("분석 실패(공시 대기 또는 잘못된 no): %s", no)
        return None

    name = detail["name"]
    is_spac = evaluator.is_spac(name)
    is_reit = evaluator.is_reit(name)
    is_spac_reit = is_spac or is_reit

    dart_data = dart.fetch_raw_demand(name)
    merged = evaluator.merge_sources(detail, dart_data)

    cp = merged.get("confirmed_price")
    if is_spac_reit:
        otc_avg = otc_min = None
    else:
        quote = scraper.get_otc_quote(
            name, confirmed_price=cp,
            sell_prices=merged.get("sell_prices"), buy_prices=merged.get("buy_prices"))
        otc_avg, otc_min = quote["avg"], quote["min"]

    metrics = evaluator.build_metrics(merged, otc_avg, skip_otc=is_spac_reit)
    # 장외 최소호가 기준 괴리율(분석가 방식)도 함께 — 평균/최소 둘 다 표시·채점
    otc_min_premium = (None if (is_spac_reit or otc_min is None)
                       else evaluator.otc_premium(otc_min, cp))
    metrics["otc_min_premium"] = otc_min_premium
    metrics["otc_min_price"] = otc_min
    metrics["otc_avg_price"] = otc_avg

    result = evaluator.evaluate_ipo_score(metrics, is_simultaneous=is_simultaneous,
                                          is_spac_reit=is_spac_reit)
    # 최소호가 기준 총점(자동알림·표시용) — 장외 칸만 최소 괴리율로 교체해 재채점
    min_metrics = {**metrics, "otc_premium": otc_min_premium}
    result_min = evaluator.evaluate_ipo_score(min_metrics, is_simultaneous=is_simultaneous,
                                              is_spac_reit=is_spac_reit)
    # 스팩은 경쟁률·확약만으로 별도 판정(리츠는 분석 제외 — spac_result=None)
    spac_result = evaluator.evaluate_spac(metrics) if is_spac else None

    return {"merged": merged, "metrics": metrics, "result": result, "result_min": result_min,
            "is_spac_reit": is_spac_reit, "is_spac": is_spac, "is_reit": is_reit,
            "spac_result": spac_result, "name": name, "no": no}


def find_no_by_name(target_name: str) -> Optional[str]:
    """청약일정 목록에서 종목명 매칭 → 고유번호(no) 반환. 없으면 None.
    스팩도 검색 가능하도록 스팩은 목록에 포함(리츠만 제외)."""
    for c in scraper.fetch_schedule(exclude_spac=False):
        if is_same_company(target_name, c["name"]):
            return c["no"]
    return None


def analyze_by_name(target_name: str) -> Optional[dict]:
    """종목명으로 분석. 청약일정에서 매칭 후 analyze_by_no 호출."""
    no = find_no_by_name(target_name)
    if not no:
        logger.info("청약일정에서 종목 미발견: %s", target_name)
        return None
    return analyze_by_no(no)
