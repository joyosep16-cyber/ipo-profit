from apscheduler.schedulers.background import BackgroundScheduler

from utils.constants import (
    WATCHLIST_STATUS_INTERESTED, WATCHLIST_STATUS_MISSED, WATCHLIST_STATUS_SUBSCRIBED,
)


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


def _run_listing_alert(target_date, notif_type: str, sender) -> None:
    """청약완료 종목 중 상장일이 target_date 인 종목에 sender 알림 발송.

    NotificationLog(notif_type, {id}-{상장일})로 중복 발송 방지. D-day/D-1
    공통 로직."""
    from database import get_watchlist, is_notified, log_notification

    for item in get_watchlist(status=WATCHLIST_STATUS_SUBSCRIBED):
        if item.get("listing_date") != target_date:
            continue
        ref_key = f"{item['id']}-{item['listing_date']}"
        if is_notified(notif_type, ref_key):
            continue
        sender(item)
        log_notification(notif_type, ref_key)


def _listing_day_job() -> None:
    """청약 신청(청약완료)한 종목 중 오늘 상장하는 종목 Discord 알림.

    매일 08:30 cron + 앱 접속 시 1회(init_app) 호출된다. NotificationLog 로
    중복 발송을 막으므로 두 경로에서 동시 호출돼도 안전하다(Render 무료플랜은
    잠들면 cron 이 안 도므로 접속 시 보강이 핵심).
    """
    try:
        from datetime import date
        from utils.discord_notifier import send_listing_day_alert
        _run_listing_alert(date.today(), "listing_day", send_listing_day_alert)
    except Exception as e:
        print(f"[Scheduler] listing_day_job error: {e}")


def _listing_dday_job() -> None:
    """청약 신청(청약완료)한 종목 중 내일 상장하는 종목 D-1 Discord 미리 알림.

    매일 18:00 cron + 앱 접속 시 1회(init_app) 호출. 중복 방지는 _listing_day_job 과 동일."""
    try:
        from datetime import date, timedelta
        from utils.discord_notifier import send_listing_dday_alert
        _run_listing_alert(date.today() + timedelta(days=1), "listing_dday", send_listing_dday_alert)
    except Exception as e:
        print(f"[Scheduler] listing_dday_job error: {e}")


def _analysis_alert_job() -> None:
    """매일 14·15·16·17시 — 청약일정 종목 수요예측 분석 후 16점+ Discord 자동 알림.

    스팩/리츠 제외, 중복 발송 방지(NotificationLog), 종목 간 예외 격리.
    설정에서 자동알림 OFF면 즉시 종료.
    """
    try:
        import os
        from database import get_setting, is_analysis_alerted, log_notification
        from utils.discord_notifier import send_analysis_score
        from analyzer import scraper, evaluator, service, config

        # 자동알림 on/off
        if get_setting("ANALYSIS_AUTO_ALERT", "1") != "1":
            return

        # DART 키 주입
        dart_key = get_setting("DART_API_KEY", "")
        if dart_key:
            os.environ["DART_API_KEY"] = dart_key

        # 임계점 (설정 우선, 기본 16)
        try:
            threshold = int(get_setting("ANALYSIS_THRESHOLD", str(config.SCORE_THRESHOLD)))
        except ValueError:
            threshold = config.SCORE_THRESHOLD

        for c in scraper.fetch_schedule():
            name = c.get("name", "")
            no = c.get("no", "")
            if evaluator.is_spac_or_reit(name):
                continue
            if is_analysis_alerted(no):
                continue
            try:
                bundle = service.analyze_by_no(no)
                if not bundle or bundle["is_spac"]:
                    continue
                total = bundle["result"].get("total")
                if total is not None and total >= threshold:
                    send_analysis_score(bundle["merged"], bundle["result"], bundle["metrics"])
                    log_notification("analysis_alert", no)
            except Exception as inner:
                print(f"[Scheduler] analysis_alert 종목 처리 오류({name}): {inner}")
    except Exception as e:
        print(f"[Scheduler] analysis_alert_job error: {e}")


def start_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone='Asia/Seoul', daemon=True)
    scheduler.add_job(_monthly_summary_job,   "cron", day=1, hour=9, minute=0)
    scheduler.add_job(_watchlist_check_job,   "cron", hour=0, minute=0)
    scheduler.add_job(_watchlist_reminder_job, "cron", hour=9, minute=0)
    # 청약 신청 종목 상장 D-1 미리 알림 — 매일 18:00 (전날 저녁)
    scheduler.add_job(_listing_dday_job, "cron", hour=18, minute=0)
    # 청약 신청 종목 상장 당일 알림 — 매일 08:30 (장 시작 전)
    scheduler.add_job(_listing_day_job, "cron", hour=8, minute=30)
    # 수요예측 분석 자동알림 — 매일 14·15·16·17시
    scheduler.add_job(_analysis_alert_job, "cron", hour="14,15,16,17", minute=0)
    scheduler.start()
    return scheduler
