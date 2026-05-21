import os

import streamlit as st


@st.cache_resource
def setup() -> dict:
    _bridge_secrets()

    from dotenv import load_dotenv
    load_dotenv()

    from database import init_db
    init_db()
    _apply_db_settings()

    public_url = _start_ngrok()
    _start_scheduler()
    _check_monthly_summary()

    if public_url:
        try:
            from utils.discord_notifier import send_app_started
            send_app_started(public_url)
        except Exception:
            pass

    return {"public_url": public_url}


def _apply_db_settings() -> None:
    try:
        from database import get_setting
        for key in ["DISCORD_WEBHOOK_URL", "HIGH_RETURN_THRESHOLD", "NGROK_AUTH_TOKEN", "MONTHLY_GOAL", "YEARLY_GOAL"]:
            val = get_setting(key)
            if val:
                os.environ[key] = val
    except Exception:
        pass


def _bridge_secrets() -> None:
    keys = ["DISCORD_WEBHOOK_URL", "NGROK_AUTH_TOKEN",
            "HIGH_RETURN_THRESHOLD", "DATABASE_URL"]
    try:
        for key in keys:
            val = st.secrets.get(key)
            if val and not os.getenv(key):
                os.environ[key] = str(val)
    except Exception:
        pass


def _start_ngrok() -> str | None:
    token = os.getenv("NGROK_AUTH_TOKEN", "").strip()
    if not token:
        return None
    try:
        from pyngrok import conf, ngrok
        import atexit

        conf.get_default().auth_token = token

        # 앱 종료 시 ngrok 세션을 깔끔하게 끊어 서버 세션 슬롯 즉시 반환
        atexit.register(_cleanup_ngrok)

        # 로컬 API(4040)로 이미 살아있는 터널 재사용
        try:
            import requests as _req
            resp = _req.get("http://localhost:4040/api/tunnels", timeout=2)
            if resp.ok:
                for t in resp.json().get("tunnels", []):
                    if t.get("proto") == "https":
                        return t["public_url"]
        except Exception:
            pass

        tunnels = ngrok.get_tunnels()
        if tunnels:
            return tunnels[0].public_url

        # 좀비 프로세스 정리 후 새로 연결
        ngrok.kill()
        tunnel = ngrok.connect(8501)
        return tunnel.public_url
    except Exception as e:
        import re
        m = re.search(r"'(https://[^\s']+\.ngrok[^\s']*)'", str(e))
        if m:
            return m.group(1)
        return None


def _cleanup_ngrok() -> None:
    try:
        from pyngrok import ngrok
        ngrok.kill()
    except Exception:
        pass


def _start_scheduler() -> None:
    try:
        from utils.scheduler import start_scheduler
        start_scheduler()
    except Exception:
        pass


def _check_monthly_summary() -> None:
    try:
        from datetime import datetime
        from database import get_monthly_stats, is_monthly_summary_sent, log_notification
        from utils.discord_notifier import send_monthly_summary

        now = datetime.now()
        year = now.year - 1 if now.month == 1 else now.year
        month = 12 if now.month == 1 else now.month - 1

        if not is_monthly_summary_sent(year, month):
            stats = get_monthly_stats(year, month)
            if stats["count"] > 0:
                send_monthly_summary(year, month, stats)
                log_notification("monthly_summary", f"{year}-{month:02d}")
    except Exception:
        pass
