from apscheduler.schedulers.background import BackgroundScheduler

from utils.constants import WATCHLIST_STATUS_INTERESTED, WATCHLIST_STATUS_MISSED


def _monthly_summary_job() -> None:
    try:
        from datetime import datetime
        from database import get_monthly_stats, is_monthly_summary_sent, log_notification
        from utils.discord_notifier import send_monthly_summary

        now = datetime.now()
        year, month = (now.year - 1, 12) if now.month == 1 else (now.year, now.month - 1)

        if is_monthly_summary_sent(year, month):
            return

        stats = get_monthly_stats(year, month)
        if stats["count"] > 0:
            send_monthly_summary(year, month, stats)
            log_notification("monthly_summary", f"{year}-{month:02d}")
    except Exception as e:
        print(f"[Scheduler] monthly_summary_job error: {e}")


def _watchlist_check_job() -> None:
    """매일 00:00 — 청약 종료일 경과한 관심 종목 → 청약미신청 자동 처리"""
    try:
        from datetime import date
        from database import get_watchlist, update_watchlist_status
        from utils.discord_notifier import send_watchlist_missed

        today = date.today()
        for item in get_watchlist(status=WATCHLIST_STATUS_INTERESTED):
            if item["sub_end"] and item["sub_end"] < today:
                update_watchlist_status(item["id"], WATCHLIST_STATUS_MISSED)
                send_watchlist_missed(item)
    except Exception as e:
        print(f"[Scheduler] watchlist_check_job error: {e}")


def _watchlist_reminder_job() -> None:
    """매일 09:00 — 청약 마감 D-1 Discord 알림"""
    try:
        from datetime import date, timedelta
        from database import get_watchlist
        from utils.discord_notifier import send_watchlist_reminder

        tomorrow = date.today() + timedelta(days=1)
        for item in get_watchlist(status=WATCHLIST_STATUS_INTERESTED):
            if item["sub_end"] == tomorrow:
                send_watchlist_reminder(item)
    except Exception as e:
        print(f"[Scheduler] watchlist_reminder_job error: {e}")


def start_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone='Asia/Seoul', daemon=True)
    scheduler.add_job(_monthly_summary_job,   "cron", day=1, hour=9, minute=0)
    scheduler.add_job(_watchlist_check_job,   "cron", hour=0, minute=0)
    scheduler.add_job(_watchlist_reminder_job, "cron", hour=9, minute=0)
    scheduler.start()
    return scheduler
