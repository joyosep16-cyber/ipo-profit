"""분석 엔진 설정 / 상수 / 임계값.

크롤링 URL·스코어링 테이블 등 변하지 않는 상수를 모은다.
Discord 웹훅은 웹앱 DB 설정(AppSetting)으로 통일되므로 여기서 관리하지 않는다.
DART_API_KEY 는 웹앱 .env / Streamlit secrets / DB 설정에서 주입된다.
"""
import os


# ---------------------------------------------------------------------------
# 비밀값 (환경변수 — 웹앱 init_app 이 .env/secrets/DB 를 env 로 브리지함)
# ---------------------------------------------------------------------------
def get_dart_api_key() -> str:
    """호출 시점에 DART API 키를 읽는다 (런타임 주입 대응)."""
    return os.getenv("DART_API_KEY", "").strip()


# 하위 호환용 모듈 상수 (import 시점 값). 실시간 갱신은 get_dart_api_key() 사용.
DART_API_KEY = get_dart_api_key()

# ---------------------------------------------------------------------------
# 크롤링 대상 URL
# ---------------------------------------------------------------------------
SCHEDULE_LIST_URL = "https://www.38.co.kr/html/fund/index.htm?o=k"
BASE_DETAIL_URL = "https://www.38.co.kr/html/fund/?o=v&no={no}"
OTC_URL = "http://stock.38.co.kr/html/trade/trade_sellbuy/?act=search&sc_string={name}"

# ---------------------------------------------------------------------------
# 동작 파라미터
# ---------------------------------------------------------------------------
REQUEST_DELAY = 1.5                 # 매 HTTP 요청 직전 강제 대기(초) — anti-bot
REQUEST_TIMEOUT = 10                # 요청 타임아웃(초)
SCORE_THRESHOLD = 16                # 이 점수 이상이면 Discord 자동 알림 (기본값)
EXCLUDE_KEYWORDS = ["스팩", "호스팩", "리츠"]            # 스코어링 제외 키워드
SITE_ENCODING = "euc-kr"            # 38커뮤니케이션 인코딩

# Discord Embed 기본 색상
EMBED_COLOR = 0x00FF00              # 초록색 (#00FF00)

# ---------------------------------------------------------------------------
# 스코어링 테이블  (형식: (임계값, 점수) — 위에서부터 첫 매칭)
# ---------------------------------------------------------------------------
SCORE_INST_COMPETITION = [(500, 5), (450, 4), (400, 3), (350, 2), (300, 1)]  # >=
SCORE_LOCKUP = [(30, 10), (20, 8), (15, 6), (10, 4), (5, 2)]                 # >=
SCORE_CIRCULATING_EOK = [(200, 10), (500, 6), (1000, 4), (2000, 2), (3000, 1)]  # <=
SCORE_OTC_PREMIUM = [(160, 6), (100, 3), (50, 0)]   # >= ; 50 미만은 별도 -3
SCORE_OTC_PENALTY = -3                               # +50% 미만 감점
SCORE_SIMULTANEOUS_PENALTY = -2                      # 동시상장 감점

# 1억 = 100,000,000원
EOK = 100_000_000
