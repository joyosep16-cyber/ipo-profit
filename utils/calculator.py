from typing import Optional

from utils.constants import RETURN_RATE_VERY_HIGH, RETURN_RATE_HIGH, RETURN_RATE_GOOD, RETURN_RATE_FAIR


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
    return (sell_price - ipo_price) * quantity


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
