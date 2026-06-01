"""공용 유틸리티: HTTP 요청, 인코딩, 숫자 파싱, 액면분할 보정, 로깅.

- 모든 외부 요청은 ``safe_get`` 을 통해서만 나가도록 한다. 여기서 anti-bot
  대비(랜덤 UA + 요청 직전 1.5초 강제 대기)와 EUC-KR 디코딩을 일괄 처리한다.
- 38.co.kr 등 구형 TLS 사이트는 _LegacyTLSAdapter 로 SSL 핸드셰이크 우회한다.
- 스크래퍼는 ``parse_number`` 로 "47,500원", "1,234.5%" 같은 텍스트에서 숫자만 뽑는다.
"""
import io
import logging
import re
import ssl
import sys
import time
import urllib3
from typing import Optional

import requests
from requests.adapters import HTTPAdapter

from analyzer import config

# SSL 경고 억제 (구형 TLS 우회 시 발생하는 InsecureRequestWarning)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

try:
    from fake_useragent import UserAgent
    _UA = UserAgent()
except Exception:  # 네트워크/캐시 문제로 초기화 실패 시 폴백
    _UA = None

_FALLBACK_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


# ---------------------------------------------------------------------------
# 로깅
# ---------------------------------------------------------------------------
def get_logger(name: str = "ipo_analyzer") -> logging.Logger:
    """콘솔 핸들러 로거 반환 (중복 핸들러 방지).

    웹앱(Streamlit/Render) 환경에서는 표준 출력 로깅만 사용한다(파일 로깅 제외).
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")

    # Windows 콘솔 기본 인코딩(cp949)에서 한글 깨짐 방지 → UTF-8 스트림으로 강제
    stream = sys.stdout
    try:
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
        else:
            stream = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass
    console = logging.StreamHandler(stream)
    console.setFormatter(fmt)
    logger.addHandler(console)
    return logger


logger = get_logger()


# ---------------------------------------------------------------------------
# 구형 TLS 호환 어댑터
# ---------------------------------------------------------------------------
class _LegacyTLSAdapter(HTTPAdapter):
    """38.co.kr 등 구형 SSL 설정 사이트 전용 어댑터.

    Python 기본 SSL은 최신 보안 수준(SECLEVEL=2)을 강제하여
    'sslv3 alert handshake failure' 오류가 발생한다.
    SECLEVEL=1로 낮추고 인증서 검증을 비활성화해 핸드셰이크를 통과시킨다.
    """
    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        kwargs["ssl_context"] = ctx
        super().init_poolmanager(*args, **kwargs)

    def proxy_manager_for(self, proxy, **proxy_kwargs):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        proxy_kwargs["ssl_context"] = ctx
        return super().proxy_manager_for(proxy, **proxy_kwargs)


def _build_session() -> requests.Session:
    """구형 TLS 어댑터가 장착된 세션 생성."""
    session = requests.Session()
    adapter = _LegacyTLSAdapter()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


# 모듈 수준 세션 (재사용으로 커넥션 풀 유지)
_SESSION = _build_session()


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def _random_user_agent() -> str:
    if _UA is not None:
        try:
            return _UA.random
        except Exception:
            pass
    return _FALLBACK_UA


def safe_get(url: str) -> Optional[requests.Response]:
    """anti-bot 대비 + 구형 TLS 호환 GET 요청.

    - 매 요청 직전 ``time.sleep(REQUEST_DELAY)`` 무조건 적용.
    - 랜덤 User-Agent 헤더.
    - _LegacyTLSAdapter: SECLEVEL=1 + 인증서 검증 비활성 → 38.co.kr SSL 우회.
    - EUC-KR 명시 디코딩(``resp.encoding = 'euc-kr'``).
    - 실패 시 None 반환(예외를 호출부로 전파하지 않음).
    """
    time.sleep(config.REQUEST_DELAY)  # 무조건 대기 (요청 빈도 제한)
    headers = {
        "User-Agent": _random_user_agent(),
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Connection": "keep-alive",
    }
    try:
        resp = _SESSION.get(url, headers=headers, timeout=config.REQUEST_TIMEOUT, verify=False)
        resp.raise_for_status()
        # 38커뮤니케이션은 EUC-KR. 한글 깨짐 방지를 위해 명시 지정.
        resp.encoding = config.SITE_ENCODING
        return resp
    except requests.RequestException as exc:
        logger.warning("HTTP 요청 실패: %s (%s)", url, exc)
        return None


# ---------------------------------------------------------------------------
# 숫자 파싱
# ---------------------------------------------------------------------------
_NUM_RE = re.compile(r"-?\d[\d,]*\.?\d*")


def parse_number(text) -> Optional[float]:
    """텍스트에서 첫 숫자를 float 로 추출. 콤마/단위 문자 제거. 실패 시 None.

    예) "47,500 원" -> 47500.0,  "1,234.56%" -> 1234.56,  "- 주" -> None
    """
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)
    match = _NUM_RE.search(str(text))
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# 액면분할 보정
# ---------------------------------------------------------------------------
def apply_facevalue_split(price: Optional[float], face_value: Optional[float],
                          base_face_value: float = 500.0) -> Optional[float]:
    """액면분할 비율로 장외 호가를 보정.

    장외 게시판 호가는 분할 이전 액면가 기준으로 올라오는 경우가 있어,
    상세 페이지의 확정 액면가(face_value) 대비 비율로 환산한다.

    환산식: 보정가 = 호가 * (face_value / base_face_value)
    예) 기준 액면 500원, 현재 액면 100원(1/5 분할)이면 호가의 1/5 로 보정.

    face_value 가 없거나 base 와 같으면 원가 그대로 반환.
    """
    if price is None:
        return None
    if not face_value or face_value <= 0 or face_value == base_face_value:
        return price
    return price * (face_value / base_face_value)
