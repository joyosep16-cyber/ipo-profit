"""스케줄러 KST 타임존 + 상장 알림 후보/잡 단위 테스트.

핵심 회귀 방지:
  - 잡 내부 '오늘/내일'은 서버 OS 타임존과 무관하게 KST(+9) 기준이어야 한다.
  - 상장 D-day/D-1 알림 대상 = 관심목록 청약완료 ∪ IPORecord(당첨·매도가 미입력),
    (종목명, 상장일) 기준 중복 제거, 매도완료·미당첨·상장일 없음은 제외.
"""
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import database  # noqa: E402
from utils import scheduler, discord_notifier  # noqa: E402


# ---------------------------------------------------------------------------
# KST 고정 오프셋
# ---------------------------------------------------------------------------
def test_kst_offset_is_plus9():
    assert scheduler._now_kst().utcoffset() == timedelta(hours=9)


def test_today_kst_matches_utc_plus9():
    # 서버가 UTC 든 무엇이든 KST 날짜 = UTC+9 의 날짜
    expected = (datetime.now(timezone.utc) + timedelta(hours=9)).date()
    assert scheduler._today_kst() == expected


# ---------------------------------------------------------------------------
# 상장 알림 후보 집계 + D-day/D-1 발송
# ---------------------------------------------------------------------------
def _setup(monkeypatch, wl, recs):
    sent, logged, notified = [], [], set()
    monkeypatch.setattr(database, "get_watchlist", lambda status=None: wl)
    monkeypatch.setattr(database, "get_records", lambda year=None: recs)
    monkeypatch.setattr(database, "is_notified", lambda t, k: k in notified)
    monkeypatch.setattr(database, "log_notification",
                        lambda t, k=None: (notified.add(k), logged.append((t, k))))
    monkeypatch.setattr(discord_notifier, "send_listing_day_alert",
                        lambda i: sent.append(("DAY", i["stock_name"])))
    monkeypatch.setattr(discord_notifier, "send_listing_dday_alert",
                        lambda i: sent.append(("D-1", i["stock_name"])))
    return sent, logged


def test_listing_alerts_merge_dedup_and_filter(monkeypatch):
    today = scheduler._today_kst()
    tomorrow = today + timedelta(days=1)
    wl = [
        {"id": 1, "stock_name": "워치오늘", "broker": "키움", "listing_date": today,
         "ipo_price": 30000, "analysis_score": 25, "analysis_grade": "최우선"},
        {"id": 9, "stock_name": "공통종목", "broker": "NH", "listing_date": tomorrow,
         "ipo_price": 10000, "analysis_score": 18, "analysis_grade": "청약"},
    ]
    recs = [
        {"stock_name": "레코드내일", "broker": "삼성", "sub_result": "당첨",
         "sell_price": 0, "sell_date": tomorrow, "ipo_price": 20000},
        {"stock_name": "이미매도", "broker": "KB", "sub_result": "당첨",
         "sell_price": 55000, "sell_date": today, "ipo_price": 20000},
        {"stock_name": "미당첨종목", "broker": "KB", "sub_result": "미당첨",
         "sell_price": 0, "sell_date": today, "ipo_price": 20000},
        {"stock_name": "상장일없음", "broker": "KB", "sub_result": "당첨",
         "sell_price": 0, "sell_date": None, "ipo_price": 20000},
        {"stock_name": "공통종목", "broker": "NH", "sub_result": "당첨",
         "sell_price": 0, "sell_date": tomorrow, "ipo_price": 10000},
    ]
    sent, logged = _setup(monkeypatch, wl, recs)

    scheduler._listing_dday_job()
    scheduler._listing_day_job()

    assert ("DAY", "워치오늘") in sent
    assert ("D-1", "레코드내일") in sent
    assert ("D-1", "공통종목") in sent
    assert sum(1 for x in sent if x[1] == "공통종목") == 1   # 두 소스 중복 → 1회
    names = {x[1] for x in sent}
    assert {"이미매도", "미당첨종목", "상장일없음"}.isdisjoint(names)
    assert len(sent) == 3


def test_listing_alert_no_duplicate_on_rerun(monkeypatch):
    today = scheduler._today_kst()
    wl = [{"id": 1, "stock_name": "오늘상장", "broker": "키움", "listing_date": today,
           "ipo_price": 30000, "analysis_score": None, "analysis_grade": None}]
    sent, logged = _setup(monkeypatch, wl, [])
    scheduler._listing_day_job()
    scheduler._listing_day_job()   # 재실행 → NotificationLog 로 중복 차단
    assert sent == [("DAY", "오늘상장")]
    assert len(logged) == 1


def test_pending_summary_future_only_sorted(monkeypatch):
    today = scheduler._today_kst()
    wl = [
        {"id": 1, "stock_name": "대기A", "broker": "키움", "listing_date": today + timedelta(days=2),
         "ipo_price": 30000, "analysis_score": 25, "analysis_grade": "최우선"},
        {"id": 2, "stock_name": "오늘상장", "broker": "NH", "listing_date": today,
         "ipo_price": 10000, "analysis_score": 18, "analysis_grade": "청약"},
        {"id": 3, "stock_name": "과거상장", "broker": "KB", "listing_date": today - timedelta(days=3),
         "ipo_price": 10000, "analysis_score": None, "analysis_grade": None},
    ]
    batches = []
    notified = set()
    monkeypatch.setattr(database, "get_watchlist", lambda status=None: wl)
    monkeypatch.setattr(database, "get_records", lambda year=None: [])
    monkeypatch.setattr(database, "is_notified", lambda t, k: k in notified)
    monkeypatch.setattr(database, "log_notification", lambda t, k=None: notified.add(k))
    monkeypatch.setattr(discord_notifier, "send_pending_holdings_summary",
                        lambda items: batches.append([i["stock_name"] for i in items]))

    scheduler._pending_summary_job()
    scheduler._pending_summary_job()   # 같은 ISO 주 → 1회만

    assert len(batches) == 1
    assert batches[0] == ["오늘상장", "대기A"]   # 미래+오늘만, 상장일 오름차순
