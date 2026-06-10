from datetime import date


def fmt_date_long(d: date) -> str:
    """날짜를 긴 형식으로: '2026년 5월 11일'"""
    if not d:
        return "-"
    return f"{d.year}년 {d.month}월 {d.day}일"


def fmt_date_short(d: date) -> str:
    """날짜를 짧은 형식으로: '05/11'"""
    if not d:
        return "-"
    return d.strftime("%m/%d")


def fmt_listing_date(d: date | None) -> str:
    """상장일 포맷팅 (미정 처리): None → '미정', date → '2026년 5월 20일'"""
    if not d:
        return "미정"
    return f"{d.year}년 {d.month}월 {d.day}일"
