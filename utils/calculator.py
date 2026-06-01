from datetime import date, datetime
from typing import Optional

from utils.constants import (
    RETURN_RATE_VERY_HIGH, RETURN_RATE_HIGH, RETURN_RATE_GOOD, RETURN_RATE_FAIR,
    SELL_TAX_RATE_SCHEDULE, DEFAULT_SELL_TAX_RATE,
)


def resolve_sell_tax_rate(sell_date=None, schedule=None) -> float:
    """매도일 기준 증권거래세율(%)을 세율표에서 자동 선택.

    schedule: [(시작일str, 세율float), ...] 또는 [{"start":..,"rate":..}, ...].
              None 이면 코드 내장 기본표(SELL_TAX_RATE_SCHEDULE) 사용.
    매도일이 속하는 가장 최근 시작구간의 세율을 반환. 매칭 없으면 DEFAULT_SELL_TAX_RATE.
    """
    if schedule is None:
        schedule = SELL_TAX_RATE_SCHEDULE

    # 정규화 → [(date, rate)]
    norm = []
    for row in schedule:
        if isinstance(row, dict):
            start_str, r = row.get("start"), row.get("rate")
        else:
            start_str, r = row[0], row[1]
        if not start_str:
            continue
        try:
            start = datetime.strptime(str(start_str)[:10], "%Y-%m-%d").date()
            norm.append((start, float(r)))
        except (ValueError, TypeError):
            continue
    norm.sort(key=lambda x: x[0])

    if sell_date is None:
        sell_date = date.today()
    elif isinstance(sell_date, str):
        try:
            sell_date = datetime.strptime(sell_date[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            sell_date = date.today()
    elif isinstance(sell_date, datetime):
        sell_date = sell_date.date()

    rate = DEFAULT_SELL_TAX_RATE
    for start, r in norm:
        if sell_date >= start:
            rate = r
    return rate


def calc_return_rate(profit: int, ipo_price: int, quantity: int) -> Optional[float]:
    if not quantity or not ipo_price:
        return None
    return (profit / (ipo_price * quantity)) * 100


def format_krw(amount: int, signed: bool = False) -> str:
    if signed:
        if amount == 0:
            return "₩0"
        sign = "+" if amount > 0 else "-"
        return f"{sign}₩{abs(amount):,}"
    if amount >= 0:
        return f"₩{amount:,}"
    return f"-₩{abs(amount):,}"


def calc_profit(sell_price: int, ipo_price: int, quantity: int) -> int:
    """세전 매매차익 = (매도가 − 공모가) × 수량."""
    return (sell_price - ipo_price) * quantity


def calc_sell_tax(sell_price: int, quantity: int, tax_rate_pct: float) -> int:
    """매도 시 증권거래세 = 매도금액(매도가 × 수량) × 세율(%) (원 단위 반올림)."""
    if not sell_price or not quantity or not tax_rate_pct:
        return 0
    return int(round(sell_price * quantity * (tax_rate_pct / 100.0)))


def calc_net_profit(
    sell_price: int,
    ipo_price: int,
    quantity: int,
    sub_result: str = "당첨",
    fee: int = 0,
    tax_rate_pct: float = 0.0,
) -> int:
    """순수익 = 세전 매매차익 − 청약수수료 − 매도세금.

    청약 수수료는 단일 기본값(전역 설정)을 사용한다(증권사별 차등은 미적용).
    - 미당첨: 증거금 환불 시 청약 수수료도 함께 회수됨 → 순수익 = 0
    - 당첨·매도 전(매도가 0): 미실현 → 0 (수수료/세금은 매도 시 반영)
    - 당첨·매도 완료: (매도가−공모가)×수량 − 청약수수료 − 매도세금
    """
    if sub_result == "미당첨":
        return 0
    if not sell_price or sell_price <= 0:
        return 0
    gross = calc_profit(int(sell_price), int(ipo_price), int(quantity))
    tax = calc_sell_tax(int(sell_price), int(quantity), tax_rate_pct)
    return gross - int(fee) - tax


def get_win_rate(records: list) -> float:
    participated = [r for r in records if r.get("sub_result", "당첨") == "당첨"]
    if not participated:
        return 0.0
    wins = sum(1 for r in participated if r.get("profit", 0) > 0)
    return (wins / len(participated)) * 100


def get_return_label(return_rate: Optional[float], sub_result: str = "당첨") -> str:
    if sub_result == "미당첨":
        return "❌ 미당첨"
    if return_rate is None:
        return "➖ 매도 미입력"
    if return_rate >= RETURN_RATE_VERY_HIGH:
        return "🚀 초고수익"
    if return_rate >= RETURN_RATE_HIGH:
        return "🎉 고수익"
    if return_rate >= RETURN_RATE_GOOD:
        return "✨ 우수"
    if return_rate >= RETURN_RATE_FAIR:
        return "👍 양호"
    if return_rate > 0:
        return "📈 수익"
    if return_rate == 0:
        return "➖ 손익없음"
    return "📉 손실"
