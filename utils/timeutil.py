"""한국 표준시(KST) 시각 헬퍼.

서버 OS 타임존(클라우드는 보통 UTC)과 무관하게 '지금/오늘'을 KST 기준으로
계산한다. KST 는 서머타임이 없어 고정 오프셋(+9)으로 충분하며 tzdata 의존이 없다.

- now_kst():        tz-aware datetime (KST)
- today_kst():      date (KST 기준 오늘)
- now_kst_naive():  tzinfo 없는 datetime — naive DateTime 컬럼(DB 저장)용
"""
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))


def now_kst() -> datetime:
    return datetime.now(KST)


def today_kst():
    return now_kst().date()


def now_kst_naive() -> datetime:
    return now_kst().replace(tzinfo=None)
