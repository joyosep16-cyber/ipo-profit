import os
import subprocess
import sys

import streamlit as st

from database import get_setting, set_setting
from utils.config import get_env_float, get_env_int
from utils.constants import ENV_DISCORD_WEBHOOK, ENV_HIGH_RETURN_THRESHOLD, ENV_NGROK_TOKEN, ENV_MONTHLY_GOAL, ENV_YEARLY_GOAL

st.title("⚙️ 설정")

# ── Discord 알림 설정 ──────────────────────────────────────
st.subheader("💬 Discord 알림 설정")

current_webhook = get_setting(ENV_DISCORD_WEBHOOK) or os.getenv(ENV_DISCORD_WEBHOOK, "")
webhook_url = st.text_input(
    "Webhook URL",
    value=current_webhook,
    type="password",
    placeholder="https://discord.com/api/webhooks/...",
    help="Discord 채널 설정 → 연동 → 웹후크에서 URL을 복사하세요.",
)

default_threshold = get_env_float(ENV_HIGH_RETURN_THRESHOLD, 200.0)
try:
    db_threshold = get_setting(ENV_HIGH_RETURN_THRESHOLD)
    if db_threshold:
        default_threshold = float(db_threshold)
except ValueError:
    pass

threshold = st.number_input(
    "고수익 알림 기준 수익률 (%)",
    min_value=0.0,
    max_value=10000.0,
    value=default_threshold,
    step=10.0,
    help="이 수익률 이상이면 Discord에 고수익 달성 알림이 발송됩니다.",
)

col_test, _ = st.columns([1, 4])
with col_test:
    if st.button("📨 테스트 메시지 전송"):
        if not webhook_url.strip():
            st.warning("Webhook URL을 먼저 입력하세요.")
        else:
            try:
                import requests
                resp = requests.post(
                    webhook_url.strip(),
                    json={"content": "✅ 공모주 수익 관리 앱 — Discord 연결 테스트 메시지입니다."},
                    timeout=5,
                )
                if resp.status_code in (200, 204):
                    st.success("Discord 메시지 전송 성공!")
                else:
                    st.error(f"전송 실패: HTTP {resp.status_code}")
            except Exception as e:
                st.error(f"전송 오류: {e}")

st.divider()

# ── 외부 접속 설정 (ngrok) ─────────────────────────────────
st.subheader("🌐 모바일 외부 접속 설정 (ngrok)")

st.caption("ngrok 토큰을 입력하면 모바일에서도 앱에 접속할 수 있는 공개 URL이 생성됩니다.")
st.markdown("토큰 발급: [https://dashboard.ngrok.com/authtokens](https://dashboard.ngrok.com/authtokens)", unsafe_allow_html=False)

current_ngrok = get_setting(ENV_NGROK_TOKEN) or os.getenv(ENV_NGROK_TOKEN, "")
ngrok_token = st.text_input(
    "ngrok Auth Token",
    value=current_ngrok,
    type="password",
    placeholder="ngrok 인증 토큰을 입력하세요",
    help="무료 계정으로도 사용 가능합니다. 재시작 시 새 공개 URL이 Discord로 전송됩니다.",
)

st.divider()

# ── 수익 목표 설정 ─────────────────────────────────────────
st.subheader("🎯 수익 목표 설정")

default_monthly = get_env_int(ENV_MONTHLY_GOAL, 0)
try:
    db_monthly = get_setting(ENV_MONTHLY_GOAL)
    if db_monthly:
        default_monthly = int(db_monthly)
except ValueError:
    pass

default_yearly = get_env_int(ENV_YEARLY_GOAL, 0)
try:
    db_yearly = get_setting(ENV_YEARLY_GOAL)
    if db_yearly:
        default_yearly = int(db_yearly)
except ValueError:
    pass

col_m, col_y = st.columns(2)
with col_m:
    monthly_goal = st.number_input(
        "월간 목표 수익 (원)",
        min_value=0,
        value=default_monthly,
        step=100_000,
        format="%d",
        help="홈 화면에 이달 달성률 progress bar가 표시됩니다.",
    )
with col_y:
    yearly_goal = st.number_input(
        "연간 목표 수익 (원)",
        min_value=0,
        value=default_yearly,
        step=1_000_000,
        format="%d",
        help="홈 화면에 올해 달성률 progress bar가 표시됩니다.",
    )

st.divider()

if st.button("💾 설정 저장", type="primary"):
    set_setting(ENV_DISCORD_WEBHOOK, webhook_url.strip())
    set_setting(ENV_HIGH_RETURN_THRESHOLD, str(threshold))
    set_setting(ENV_NGROK_TOKEN, ngrok_token.strip())
    set_setting(ENV_MONTHLY_GOAL, str(int(monthly_goal)))
    set_setting(ENV_YEARLY_GOAL, str(int(yearly_goal)))

    if webhook_url.strip():
        os.environ[ENV_DISCORD_WEBHOOK] = webhook_url.strip()
    os.environ[ENV_HIGH_RETURN_THRESHOLD] = str(threshold)
    if ngrok_token.strip():
        os.environ[ENV_NGROK_TOKEN] = ngrok_token.strip()
    os.environ[ENV_MONTHLY_GOAL] = str(int(monthly_goal))
    os.environ[ENV_YEARLY_GOAL] = str(int(yearly_goal))

    st.success("✅ 설정이 저장되었습니다.")
    if ngrok_token.strip():
        st.info("💡 ngrok 토큰은 앱 재시작 후 반영됩니다.")

st.divider()

# 앱 종료 섹션
st.subheader("🛑 앱 종료")
st.caption("웹 브라우저와 백그라운드에서 실행 중인 Python 프로세스를 모두 종료합니다.")

col1, col2, col3 = st.columns([1, 2, 3])
with col1:
    if st.button("🛑 앱 종료", type="secondary", use_container_width=True):
        # 주요 브라우저 프로세스 종료
        for browser in ["chrome.exe", "msedge.exe", "firefox.exe"]:
            subprocess.run(["taskkill", "/IM", browser, "/F"], capture_output=True)
        os._exit(0)
