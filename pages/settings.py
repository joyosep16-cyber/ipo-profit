import os
import subprocess
import sys

import streamlit as st

from database import (
    get_setting, set_setting, get_sell_tax_schedule, set_sell_tax_schedule,
)
from utils.config import get_env_float, get_env_int
from utils.constants import (
    ENV_DISCORD_WEBHOOK, ENV_HIGH_RETURN_THRESHOLD, ENV_NGROK_TOKEN,
    ENV_MONTHLY_GOAL, ENV_YEARLY_GOAL, ENV_ENABLE_CLOUD_SYNC, ENV_NEON_DATABASE_URL,
    ENV_SUBSCRIPTION_FEE, DEFAULT_SUBSCRIPTION_FEE,
)

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

# ── 데이터 동기화 설정 ─────────────────────────────────────
st.subheader("🔄 데이터 동기화")

st.caption("✅ ON: Neon PostgreSQL (클라우드 동기화 - 로컬↔모바일 데이터 동일)")
st.caption("☐ OFF: 로컬 SQLite (이 PC에만 저장 - 모바일과 분리)")

# 현재 설정값 읽기
current_sync = get_setting(ENV_ENABLE_CLOUD_SYNC) or os.getenv(ENV_ENABLE_CLOUD_SYNC, "false")
is_cloud_sync = current_sync.lower() == "true"

# 체크박스
enable_sync = st.checkbox(
    "🌐 클라우드 데이터 동기화 활성화",
    value=is_cloud_sync,
    help="ON: Neon PostgreSQL 사용 | OFF: 로컬 SQLite 사용\n앱 재시작 후 적용됨"
)

# Neon PostgreSQL 주소 입력 (체크박스 ON 시 필수)
current_neon = os.getenv(ENV_NEON_DATABASE_URL) or get_setting(ENV_NEON_DATABASE_URL) or ""
neon_url_input = st.text_input(
    "Neon PostgreSQL 주소 (DATABASE_URL)",
    value=current_neon,
    type="password",
    placeholder="postgresql://user:password@ep-xxx.aws.neon.tech/neondb?sslmode=require",
    help="neon.tech 에서 발급받은 연결 문자열. 클라우드 동기화를 켜려면 반드시 입력하세요.",
    disabled=not enable_sync,
)

st.info(
    "⚠️ 설정 변경 후 앱을 재시작하세요.\n"
    "Streamlit이 자동으로 재시작되면서 새로운 데이터베이스가 적용됩니다."
)

st.divider()

# ── 공모주 분석 설정 (analyzer) ────────────────────────────
st.subheader("🔍 공모주 분석 설정")
st.caption("38커뮤니케이션 수요예측 분석 + DART 교차검증용 설정입니다. "
           "분석 자동알림은 위의 Discord 웹훅을 공유합니다.")

current_dart = get_setting("DART_API_KEY") or os.getenv("DART_API_KEY", "")
dart_api_key = st.text_input(
    "DART API 키 (OpenDART)",
    value=current_dart,
    type="password",
    placeholder="opendart.fss.or.kr 에서 무료 발급",
    help="입력 시 기관 신청수량·확약수량을 DART 공식 공시로 교차검증합니다. 없으면 38커뮤니케이션 단독 분석.",
)

try:
    default_anal_threshold = int(get_setting("ANALYSIS_THRESHOLD") or 16)
except ValueError:
    default_anal_threshold = 16

col_at, col_aa = st.columns(2)
with col_at:
    analysis_threshold = st.number_input(
        "분석 자동알림 임계점 (점)",
        min_value=0, max_value=31, value=default_anal_threshold, step=1,
        help="이 점수 이상인 종목을 매일 14·15·16·17시에 Discord로 자동 알립니다.",
    )
with col_aa:
    auto_alert = st.checkbox(
        "분석 자동알림 활성화",
        value=(get_setting("ANALYSIS_AUTO_ALERT", "1") == "1"),
        help="끄면 스케줄러가 분석 자동알림을 발송하지 않습니다.",
    )

st.divider()

# ── 비용 설정 (청약 수수료 / 매도 세금) ────────────────────
st.subheader("💸 비용 설정 (수수료·세금)")
st.caption("순수익 = 매매차익 − 청약수수료 − 매도세금. 데이터 입력 시 자동 차감됩니다.")
st.caption("※ 증권사 매도 수수료는 증권사·계좌마다 달라 반영하지 않습니다.")

try:
    default_fee = int(float(get_setting(ENV_SUBSCRIPTION_FEE) or DEFAULT_SUBSCRIPTION_FEE))
except (ValueError, TypeError):
    default_fee = DEFAULT_SUBSCRIPTION_FEE

subscription_fee = st.number_input(
    "청약 수수료 (원/건)",
    min_value=0, max_value=100000, value=default_fee, step=500,
    help="청약 1건당 증권사 수수료. 당첨 시 차감, 미당첨은 환불(0원). (보통 2,000원, 일부 무료)",
)

st.markdown("**매도 증권거래세율 (%) — 적용 시작일별 자동 적용**")
st.caption("매도일이 속하는 구간의 세율이 자동 적용됩니다. 법 개정 시 행을 추가하세요. "
           "(예: 2025-01-01 / 0.15) · 국세청·KRX 고시 기준으로 입력")

import pandas as _pd
_sched = get_sell_tax_schedule()   # [{"start","rate"}, ...]
_sched_df = _pd.DataFrame(_sched if _sched else [{"start": "2025-01-01", "rate": 0.15}])
tax_schedule_edited = st.data_editor(
    _sched_df,
    num_rows="dynamic",
    use_container_width=True,
    column_config={
        "start": st.column_config.TextColumn("적용 시작일 (YYYY-MM-DD)", required=True),
        "rate": st.column_config.NumberColumn("세율 (%)", min_value=0.0, max_value=1.0,
                                              step=0.01, format="%.3f", required=True),
    },
    key="tax_schedule_editor",
)

st.divider()

if st.button("💾 설정 저장", type="primary"):
    set_setting("DART_API_KEY", dart_api_key.strip())
    set_setting("ANALYSIS_THRESHOLD", str(int(analysis_threshold)))
    set_setting("ANALYSIS_AUTO_ALERT", "1" if auto_alert else "0")
    set_setting(ENV_SUBSCRIPTION_FEE, str(int(subscription_fee)))
    os.environ[ENV_SUBSCRIPTION_FEE] = str(int(subscription_fee))
    # 매도 세율 자동표 저장 (data_editor → list[dict])
    try:
        _rows = tax_schedule_edited.to_dict("records")
    except AttributeError:
        _rows = list(tax_schedule_edited)
    set_sell_tax_schedule(_rows)
    if dart_api_key.strip():
        os.environ["DART_API_KEY"] = dart_api_key.strip()
    set_setting(ENV_DISCORD_WEBHOOK, webhook_url.strip())
    set_setting(ENV_HIGH_RETURN_THRESHOLD, str(threshold))
    set_setting(ENV_NGROK_TOKEN, ngrok_token.strip())
    set_setting(ENV_MONTHLY_GOAL, str(int(monthly_goal)))
    set_setting(ENV_YEARLY_GOAL, str(int(yearly_goal)))

    # 클라우드 동기화 설정 추가
    sync_enabled = "true" if enable_sync else "false"
    set_setting(ENV_ENABLE_CLOUD_SYNC, sync_enabled)

    if webhook_url.strip():
        os.environ[ENV_DISCORD_WEBHOOK] = webhook_url.strip()
    os.environ[ENV_HIGH_RETURN_THRESHOLD] = str(threshold)
    if ngrok_token.strip():
        os.environ[ENV_NGROK_TOKEN] = ngrok_token.strip()
    os.environ[ENV_MONTHLY_GOAL] = str(int(monthly_goal))
    os.environ[ENV_YEARLY_GOAL] = str(int(yearly_goal))

    # 클라우드 동기화 환경 변수 설정
    if enable_sync:
        # 입력 필드 우선 → 없으면 기존 env/DB 설정
        neon_url = (neon_url_input.strip()
                    or os.getenv("NEON_DATABASE_URL")
                    or get_setting(ENV_NEON_DATABASE_URL))
        if not neon_url:
            st.error("❌ Neon PostgreSQL 주소를 입력하지 않았습니다.\n"
                     "위 'Neon PostgreSQL 주소' 칸에 연결 문자열을 입력하거나, "
                     "클라우드 동기화를 끄고 로컬(SQLite)로 사용하세요.")
        else:
            os.environ["DATABASE_URL"] = neon_url
            set_setting(ENV_NEON_DATABASE_URL, neon_url)
            st.success("✅ 설정이 저장되었습니다.")
            st.success("✅ 클라우드 동기화 활성화됨!")
            st.warning("🔄 앱을 재시작하세요. (F5 새로고침 또는 앱 재실행)")
    else:
        if "DATABASE_URL" in os.environ:
            del os.environ["DATABASE_URL"]
        st.success("✅ 설정이 저장되었습니다.")
        st.success("✅ 로컬 SQLite 사용으로 변경됨!")
        st.warning("🔄 앱을 재시작하세요. (F5 새로고침 또는 앱 재실행)")

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
