"""DART(전자공시) OpenAPI 연동 — 기관 수요예측 원본 수량 수집.

흐름:
  1. 회사명으로 list.json 검색 → rcept_no(접수번호) 확보 (최근 90일)
  2. 가장 최신 '발행조건확정' 증권신고서 ZIP 다운로드
  3. ZIP 내 모든 .htm 파일 스캔 → '수요예측 결과' 섹션 파일 탐색
  4. 해당 파일에서 기관 총 신청수량·확약 수량·배정물량 추출

🚨 산식 주의: 의무보유확약 비율 분모 = 기관 총 신청수량 (총공모주식수 아님!)
🚨 DART 응답은 UTF-8 → safe_get(EUC-KR 강제) 대신 requests 직접 호출.
"""
import io
import time
import zipfile
from datetime import datetime, timedelta
from typing import Optional

import requests
from bs4 import BeautifulSoup

from analyzer import config
from analyzer.normalizer import is_same_company
from analyzer.net import logger, parse_number

# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------
DART_BASE = "https://opendart.fss.or.kr/api"
DART_DELAY = 1.2          # DART 서버 부하 방지 (요청 간 최소 대기)
DART_TIMEOUT = 30

# ZIP 내 수요예측 결과 섹션을 식별하는 키워드
_DEMAND_KEYWORDS = ("수요예측 결과", "기관투자자의 청약", "수요예측결과", "기관투자자 수요예측")
# 확약 기간 라벨 (합산 대상)
_LOCKUP_PERIODS = ("6개월", "3개월", "1개월", "15일")


# ---------------------------------------------------------------------------
# 내부 헬퍼: DART API GET
# ---------------------------------------------------------------------------
def _dart_get(endpoint: str, params: dict) -> Optional[dict]:
    """DART REST API GET. UTF-8 응답 — EUC-KR 강제 금지."""
    time.sleep(DART_DELAY)
    params = {**params, "crtfc_key": config.get_dart_api_key()}
    try:
        resp = requests.get(
            f"{DART_BASE}/{endpoint}", params=params, timeout=DART_TIMEOUT
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.warning("DART API 오류(%s): %s", endpoint, exc)
        return None


# ---------------------------------------------------------------------------
# Step 1: 공시 목록 검색
# ---------------------------------------------------------------------------
def _search_disclosures(corp_name: str) -> list[dict]:
    """회사명으로 최근 90일 발행공시(증권신고서·투자설명서·정정) 목록 반환.

    수요예측결과는 '발행조건확정 증권신고서' 또는 '투자설명서'에 담겨 있다.
    pblntf_detail_ty 필터를 제거해 발행공시 전체를 가져온 뒤,
    제목 우선순위로 최적 문서를 선택한다. (C001만 조회 시 실적보고서가 먼저 잡히는 문제 해결)
    """
    bgn_de = (datetime.now() - timedelta(days=90)).strftime("%Y%m%d")
    # pblntf_ty=F: 발행공시 전체 (증권신고서·투자설명서·증권발행실적보고서 포함)
    data = _dart_get("list.json", {
        "corp_name": corp_name,
        "pblntf_ty": "F",   # 발행공시 카테고리 전체
        "bgn_de": bgn_de,
        "page_count": "20",
    })
    if not data or data.get("status") != "000":
        return []
    return data.get("list", [])


# 문서 제목 우선순위 — 수요예측 결과가 담긴 확률이 높은 순서
_TITLE_PRIORITY = [
    "발행조건확정",   # 최우선: 확정 공모가·수요예측 결과 포함
    "투자설명서",     # 투자설명서에도 수요예측 결과 섹션 존재
    "기재정정",       # 정정신고서
    "증권신고서",     # 원본 신고서
]
# 이 제목을 가진 문서는 수요예측 결과 미포함 → 스킵
_TITLE_BLACKLIST = ("발행실적보고서", "분기보고서", "사업보고서", "반기보고서")


def _find_best_disclosure(items: list[dict], corp_name: str) -> Optional[dict]:
    """공시 목록에서 기업명 정규화 매칭 + 제목 우선순위로 최적 문서 선택.

    우선순위: 발행조건확정 > 투자설명서 > 기재정정 > 증권신고서
    발행실적보고서·정기보고서는 제외.
    """
    # 블랙리스트 필터링
    filtered = [
        item for item in items
        if not any(kw in item.get("report_nm", "") for kw in _TITLE_BLACKLIST)
    ]

    for priority_kw in _TITLE_PRIORITY:
        for item in filtered:
            if not is_same_company(corp_name, item.get("corp_name", "")):
                continue
            if priority_kw in item.get("report_nm", ""):
                return item

    # 우선순위 매칭 실패 → 이름 매칭되는 첫 번째 비블랙리스트 항목
    for item in filtered:
        if is_same_company(corp_name, item.get("corp_name", "")):
            return item

    return None


# ---------------------------------------------------------------------------
# Step 2: ZIP 다운로드 + HTM 탐색
# ---------------------------------------------------------------------------
def _download_and_find_htm(rcept_no: str) -> Optional[BeautifulSoup]:
    """공시 ZIP 다운로드 → 모든 .htm 스캔 → 수요예측 결과 섹션 파일 반환.

    ZIP 안에는 수십 개의 .htm이 분할 저장되어 있으므로,
    각 파일의 텍스트를 읽어 DEMAND_KEYWORDS 포함 여부로 핵심 파일을 탐색한다.
    """
    time.sleep(DART_DELAY)
    try:
        resp = requests.get(
            f"{DART_BASE}/document.json",
            params={"crtfc_key": config.get_dart_api_key(), "rcept_no": rcept_no},
            timeout=DART_TIMEOUT,
        )
        resp.raise_for_status()
    except Exception as exc:
        logger.warning("DART 문서 다운로드 실패(%s): %s", rcept_no, exc)
        return None

    try:
        zf = zipfile.ZipFile(io.BytesIO(resp.content))
    except zipfile.BadZipFile:
        logger.warning("DART ZIP 손상 또는 비ZIP 응답: %s", rcept_no)
        return None

    htm_files = sorted(n for n in zf.namelist() if n.lower().endswith(".htm"))
    logger.info("DART ZIP(%s) — .htm 파일 %d개 스캔 시작", rcept_no, len(htm_files))

    for fname in htm_files:
        try:
            raw = zf.read(fname)
            # UTF-8 → EUC-KR 순서로 디코딩 시도
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                text = raw.decode("euc-kr", errors="replace")

            if any(kw in text for kw in _DEMAND_KEYWORDS):
                logger.info("수요예측 섹션 파일 발견: %s", fname)
                return BeautifulSoup(text, "lxml")
        except Exception as exc:
            logger.debug("HTM 읽기 실패(%s): %s", fname, exc)
            continue

    logger.warning("ZIP 내 수요예측 결과 섹션 미발견: %s", rcept_no)
    return None


# ---------------------------------------------------------------------------
# Step 3: 수요예측 결과 표 파싱
# ---------------------------------------------------------------------------
def _parse_demand_table(soup: BeautifulSoup) -> Optional[dict]:
    """수요예측 결과 HTM에서 기관 신청수량·확약수량·배정물량 추출.

    🚨 확약 비율 분모 = inst_total_demand (기관 총 신청수량) — 총공모주식수 아님!
    """
    inst_total: Optional[float] = None
    lockup_total = 0.0
    inst_alloc: Optional[float] = None

    for table in soup.find_all("table"):
        ttext = table.get_text(" ", strip=True)

        # ── 기관 총 신청수량 ──────────────────────────────────────────
        # 헤더: "참여건수 (단위:건)" | "신청주식수 (단위:주)"
        # 데이터: 2,329 | 1,444,988,385
        if inst_total is None and "참여건수" in ttext and "신청주식수" in ttext:
            rows = table.find_all("tr")
            for i, row in enumerate(rows):
                if "참여건수" not in row.get_text(" ", strip=True):
                    continue
                for j in range(i + 1, min(i + 4, len(rows))):
                    for cell in rows[j].find_all(["td", "th"]):
                        n = parse_number(cell.get_text(strip=True))
                        if n is not None and n >= 100_000_000:   # 1억 이상
                            inst_total = n
                            break
                    if inst_total:
                        break
                break

        # ── 의무보유확약 수량 ─────────────────────────────────────────
        # 헤더: 6개월 확약 | 3개월 확약 | 1개월 확약 | 15일 확약
        if any(p in ttext for p in _LOCKUP_PERIODS) and "미확약" in ttext:
            rows = table.find_all("tr")
            for row in rows:
                rtext = row.get_text(" ", strip=True)
                if not any(p in rtext for p in _LOCKUP_PERIODS):
                    continue
                if "미확약" in rtext or "합계" in rtext or "총" in rtext:
                    continue
                for cell in row.find_all(["td", "th"]):
                    n = parse_number(cell.get_text(strip=True))
                    if n is not None and n >= 1:
                        lockup_total += n
                        break

        # ── 기관 배정물량 ─────────────────────────────────────────────
        # "기관투자자등 X주 (75%)" 형태의 셀
        if inst_alloc is None and "기관" in ttext and ("배정" in ttext or "75" in ttext):
            for row in table.find_all("tr"):
                rtext = row.get_text(" ", strip=True)
                if "기관" not in rtext:
                    continue
                for cell in row.find_all(["td", "th"]):
                    n = parse_number(cell.get_text(strip=True))
                    if n is not None and 10_000 < n < 100_000_000:
                        inst_alloc = n
                        break
                if inst_alloc:
                    break

    if inst_total is None:
        return None   # 핵심 수치 미확보 → 폴백 트리거

    return {
        "inst_total_demand": inst_total,
        "lockup_qty": lockup_total,
        "inst_allocation": inst_alloc,
    }


# ---------------------------------------------------------------------------
# 공개 API
# ---------------------------------------------------------------------------
def fetch_raw_demand(corp_name: str) -> Optional[dict]:
    """DART에서 기관 수요예측 원본 수량 dict 반환.

    반환 dict:
      inst_total_demand: 기관 총 신청수량 (주)
      lockup_qty:        15일~6개월 확약 수량 합계 (주)
      inst_allocation:   기관 배정물량 (주, 없으면 None)
      corp_code, rcept_no, source: 메타 정보

    DART_API_KEY 미설정 또는 조회 실패 시 None 반환 → 38커뮤니케이션 폴백.
    """
    if not config.get_dart_api_key():
        logger.debug("DART_API_KEY 미설정 → DART 교차검증 스킵")
        return None

    logger.info("DART 조회 시작: %s", corp_name)

    # 1) 공시 목록 검색 (원본 이름 → 실패 시 정규화 이름으로 재시도)
    items = _search_disclosures(corp_name)
    if not items:
        from analyzer.normalizer import normalize
        items = _search_disclosures(normalize(corp_name))
    if not items:
        logger.warning("DART 공시 없음(최근 90일): %s", corp_name)
        return None

    target = _find_best_disclosure(items, corp_name)
    if not target:
        return None

    rcept_no = target["rcept_no"]
    logger.info("DART 대상 공시: [%s] %s", rcept_no, target.get("report_nm", ""))

    # 2) ZIP 다운로드 + HTM 탐색
    soup = _download_and_find_htm(rcept_no)
    if not soup:
        return None

    # 3) 표 파싱
    result = _parse_demand_table(soup)
    if not result:
        logger.warning("DART 수요예측 표 파싱 실패: %s", corp_name)
        return None

    result.update({
        "corp_code": target.get("corp_code", ""),
        "rcept_no": rcept_no,
        "source": "DART",
    })
    logger.info(
        "DART 수량 확보 완료: %s | 총신청=%s | 확약=%s | 배정=%s",
        corp_name,
        f"{result['inst_total_demand']:,.0f}",
        f"{result['lockup_qty']:,.0f}",
        f"{result['inst_allocation']:,.0f}" if result['inst_allocation'] else "-",
    )
    return result
