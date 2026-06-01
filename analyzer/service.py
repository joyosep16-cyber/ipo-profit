"""분석 파이프라인 오케스트레이션 (페이지·스케줄러 공용).

흐름: fetch_detail → DART 교차검증 → merge → (스팩/리츠 아니면) 장외가 → 산식 → 스코어링
페이지(pages/analysis.py)와 스케줄러(utils/scheduler.py)가 동일 로직을 재사용한다.
"""
from typing import Optional

from analyzer import dart, evaluator, scraper
from analyzer.net import logger
from analyzer.normalizer import is_same_company


def analyze_by_no(no: str) -> Optional[dict]:
    """고유번호(no)로 1종목 분석. 결과 번들 dict 반환, 실패 시 None.

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
    is_spac = evaluator.is_spac_or_reit(name)

    dart_data = dart.fetch_raw_demand(name)
    merged = evaluator.merge_sources(detail, dart_data)

    if is_spac:
        otc_price = None
    else:
        otc_price = scraper.get_otc_price(
            name,
            face_value=merged.get("face_value"),
            confirmed_price=merged.get("confirmed_price"),
            sell_prices=merged.get("sell_prices"),
            buy_prices=merged.get("buy_prices"),
        )

    metrics = evaluator.build_metrics(merged, otc_price, skip_otc=is_spac)
    result = evaluator.evaluate_ipo_score(metrics, is_simultaneous=False,
                                          is_spac_reit=is_spac)

    return {"merged": merged, "metrics": metrics, "result": result,
            "is_spac": is_spac, "name": name, "no": no}


def find_no_by_name(target_name: str) -> Optional[str]:
    """청약일정 목록에서 종목명 매칭 → 고유번호(no) 반환. 없으면 None."""
    for c in scraper.fetch_schedule():
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
