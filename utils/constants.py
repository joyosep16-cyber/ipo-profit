# 앱 버전 정보
APP_VERSION = "2.1.0"
APP_NAME = "공모주 수익 관리"
APP_DESCRIPTION = "38.co.kr 스크래퍼 + 날짜 보정 + 순수익 계산"
LAST_UPDATE = "2026-06-10"

# 증권사 목록
BROKERS = [
    "미정",
    "미래에셋증권", "NH투자증권", "한국투자증권", "삼성증권",
    "KB증권", "신한투자증권", "하나증권", "메리츠증권",
    "키움증권", "대신증권", "교보증권", "현대차증권",
    "신영증권", "한화투자증권", "DB금융투자", "SK증권",
    "이베스트투자증권", "유진투자증권", "IBK투자증권", "BNK투자증권",
    "다올투자증권", "카카오페이증권", "토스증권", "흥국증권",
    "케이프투자증권", "상상인증권", "코리아에셋투자증권", "한국포스증권",
    "우리투자증권", "기타",
]

# 청약방식
SUB_TYPES = ["균등", "비례"]

# 관심목록 상태
WATCHLIST_STATUS_INTERESTED = "관심"
WATCHLIST_STATUS_SUBSCRIBED = "청약완료"
WATCHLIST_STATUS_MISSED = "청약미신청"

# 환경변수 키
ENV_DISCORD_WEBHOOK = "DISCORD_WEBHOOK_URL"
ENV_NGROK_TOKEN = "NGROK_AUTH_TOKEN"
ENV_HIGH_RETURN_THRESHOLD = "HIGH_RETURN_THRESHOLD"
ENV_MONTHLY_GOAL = "MONTHLY_GOAL"
ENV_YEARLY_GOAL = "YEARLY_GOAL"
ENV_DATABASE_URL = "DATABASE_URL"
ENV_ENABLE_CLOUD_SYNC = "ENABLE_CLOUD_SYNC"
ENV_NEON_DATABASE_URL = "NEON_DATABASE_URL"
ENV_SUBSCRIPTION_FEE = "SUBSCRIPTION_FEE"   # 청약 수수료 (원/건)
ENV_SELL_TAX_RATE = "SELL_TAX_RATE"         # 매도 시 증권거래세율 (%)

# 비용 기본값
DEFAULT_SUBSCRIPTION_FEE = 2000   # 청약 수수료 기본 2,000원
DEFAULT_SELL_TAX_RATE = 0.20      # 증권거래세 기본값 (자동표 미스 시 폴백, 2026년 기준 0.20%)

# 증권거래세율 자동 적용표 (적용 시작일 → 세율%, 코스피·코스닥 공통)
# 매도일이 속하는 구간의 세율을 자동 선택한다.
# ※ 법 개정 시 (시작일, 세율) 한 줄만 추가하면 됨. 정확한 최신값은 국세청/KRX 고시 확인.
#   2023: 0.20% / 2024: 0.18% / 2025: 0.15% (단계적 인하)
#   2026~: 0.20% (금투세 폐지에 따른 환원 — 코스피 0.05%+농특세0.15%, 코스닥 0.20%)
SELL_TAX_RATE_SCHEDULE = [
    ("2023-01-01", 0.20),
    ("2024-01-01", 0.18),
    ("2025-01-01", 0.15),
    ("2026-01-01", 0.20),
]

# 수익률 판정 기준 (%)
RETURN_RATE_VERY_HIGH = 300
RETURN_RATE_HIGH = 200
RETURN_RATE_GOOD = 100
RETURN_RATE_FAIR = 50

# 일자 관련 기준값
IPO_DATE_THRESHOLD_DAYS = 60
SELL_PRICE_PENDING_DAYS = 7

# 색상 맵
SUB_TYPE_COLORS = {
    "균등": "#00b894",
    "비례": "#6c5ce7",
}

PROFIT_COLORS = {
    "수익": "#0984e3",
    "손실": "#d63031",
}
