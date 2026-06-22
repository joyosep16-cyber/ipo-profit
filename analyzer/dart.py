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
import warnings
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timedelta
from typing import Optional

import requests
from bs4 import BeautifulSoup

try:                                   # bs4 가 DART .xml 을 HTML 파서로 읽을 때의 경고 억제
    from bs4 import XMLParsedAsHTMLWarning
    warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
except ImportError:
    pass

from analyzer import config
from analyzer.normalizer import normalize
from analyzer.net import logger, parse_number

# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------
DART_BASE = "https://opendart.fss.or.kr/api"
DART_DELAY = 1.2          # DART 서버 부하 방지 (요청 간 최소 대기)
DART_TIMEOUT = 30

# ZIP 내 수요예측 결과 섹션을 식별하는 키워드
_DEMAND_KEYWORDS = ("수요예측 결과", "기관투자자의 청약", "수요예측결과", "기관투자자 수요예측")
# ZIP 내 공모 후 유통가능물량(주주현황) 섹션 식별 키워드
_CIRC_KEYWORDS = ("유통가능물량", "유통가능 물량", "공모후 유통", "공모 후 유통")
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
# Step 0: 고유번호(corp_code) 조회 — list.json 은 corp_name 필터를 받지 않는다.
# ---------------------------------------------------------------------------
_CORP_CODE_URL = "https://opendart.fss.or.kr/api/corpCode.xml"
_corp_code_map: Optional[dict] = None   # {corp_name: [(corp_code, stock_code, modify_date), ...]}


def _load_corp_code_map() -> dict:
    """DART 전체 기업 고유번호(corpCode.xml)를 1회 다운로드해 {회사명: [...]} 로 캐시.

    list.json 은 corp_name 으로 필터링되지 않으므로(무시됨), 회사명→corp_code 매핑이 필수다.
    """
    global _corp_code_map
    if _corp_code_map is not None:
        return _corp_code_map
    _corp_code_map = {}
    try:
        time.sleep(DART_DELAY)
        resp = requests.get(_CORP_CODE_URL,
                            params={"crtfc_key": config.get_dart_api_key()},
                            timeout=DART_TIMEOUT)
        resp.raise_for_status()
        zf = zipfile.ZipFile(io.BytesIO(resp.content))
        root = ET.fromstring(zf.read(zf.namelist()[0]))
        for e in root.iter("list"):
            nm = (e.findtext("corp_name") or "").strip()
            if not nm:
                continue
            _corp_code_map.setdefault(nm, []).append((
                (e.findtext("corp_code") or "").strip(),
                (e.findtext("stock_code") or "").strip(),
                (e.findtext("modify_date") or "").strip(),
            ))
        logger.info("DART corpCode 로드 완료: 회사명 %d개", len(_corp_code_map))
    except Exception as exc:
        logger.warning("DART corpCode 로드 실패: %s", exc)
        _corp_code_map = {}
    return _corp_code_map


def _get_corp_codes(corp_name: str) -> list[str]:
    """회사명 → corp_code 후보 리스트(최신 수정일 순). 정확 매칭 후 정규화 매칭 폴백."""
    m = _load_corp_code_map()
    cands = list(m.get(corp_name) or m.get(corp_name.strip()) or [])
    if not cands:
        target = normalize(corp_name)
        for nm, lst in m.items():
            if normalize(nm) == target:
                cands.extend(lst)
    # 최신 수정일(modify_date) 순으로 corp_code 반환
    return [c[0] for c in sorted(cands, key=lambda x: x[2], reverse=True) if c[0]]


# ---------------------------------------------------------------------------
# Step 1: 공시 목록 검색 (corp_code 기준)
# ---------------------------------------------------------------------------
def _search_disclosures(corp_code: str) -> list[dict]:
    """corp_code 로 최근 120일 공시 목록 반환(전체 유형 — 제목 우선순위로 선별).

    ⚠️ pblntf_ty 는 사용하지 않는다: 'F'는 외부감사관련(감사보고서)이라 증권신고서가
    빠졌던 버그가 있었다. 전체를 받아 _find_best_disclosure 의 제목 우선순위로 고른다.
    """
    bgn_de = (datetime.now() - timedelta(days=120)).strftime("%Y%m%d")
    data = _dart_get("list.json", {
        "corp_code": corp_code,
        "bgn_de": bgn_de,
        "page_count": "100",
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
_TITLE_BLACKLIST = ("발행실적보고서", "분기보고서", "사업보고서", "반기보고서", "감사보고서")


def _find_best_disclosure(items: list[dict]) -> Optional[dict]:
    """공시 목록(이미 corp_code 로 필터됨)에서 제목 우선순위로 최적 문서 선택.

    우선순위: 발행조건확정 > 투자설명서 > 기재정정 > 증권신고서 (수요예측 결과·확정가 포함)
    감사보고서·정기보고서·발행실적보고서는 제외.
    """
    filtered = [
        item for item in items
        if not any(kw in item.get("report_nm", "") for kw in _TITLE_BLACKLIST)
    ]
    for priority_kw in _TITLE_PRIORITY:
        for item in filtered:
            if priority_kw in item.get("report_nm", ""):
                return item
    return filtered[0] if filtered else None


def _find_full_registration(items: list[dict], exclude_rcept: str = "") -> Optional[dict]:
    """유통가능물량(주주현황)이 담긴 '본문' 증권신고서를 선택.

    '발행조건확정' 증권신고서는 확정공모가만 담은 짧은 정정본이라 유통가능물량 표가 없다.
    따라서 '증권신고서' 또는 '투자설명서'이면서 '발행조건확정'이 아닌 최신 문서를 고른다.
    (items 는 DART 가 최신순으로 반환)
    """
    for item in items:
        nm = item.get("report_nm", "")
        if item.get("rcept_no") == exclude_rcept:
            continue
        if ("증권신고서" in nm or "투자설명서" in nm) and "발행조건확정" not in nm:
            return item
    return None


# ---------------------------------------------------------------------------
# Step 2: ZIP 다운로드 + HTM 탐색
# ---------------------------------------------------------------------------
def _download_htm_texts(rcept_no: str) -> list:
    """공시 ZIP 다운로드 → [(fname, text), ...] 반환 (실패 시 빈 리스트).

    ZIP 안에는 수십 개의 .htm이 분할 저장되어 있다. 한 번 받아서 모든 텍스트를
    돌려주면, 수요예측 결과·유통가능물량 등 여러 섹션을 추가 다운로드 없이 찾을 수 있다.
    """
    time.sleep(DART_DELAY)
    try:
        # ⚠️ 문서 원문 엔드포인트는 document.xml (document.json 은 'status 101 잘못된 URL')
        resp = requests.get(
            f"{DART_BASE}/document.xml",
            params={"crtfc_key": config.get_dart_api_key(), "rcept_no": rcept_no},
            timeout=DART_TIMEOUT,
        )
        resp.raise_for_status()
    except Exception as exc:
        logger.warning("DART 문서 다운로드 실패(%s): %s", rcept_no, exc)
        return []

    try:
        zf = zipfile.ZipFile(io.BytesIO(resp.content))
    except zipfile.BadZipFile:
        logger.warning("DART ZIP 손상 또는 비ZIP 응답: %s", rcept_no)
        return []

    # DART 원문은 .xml(DSD) 로 저장된다. 구버전 .htm 도 함께 허용.
    doc_files = sorted(n for n in zf.namelist() if n.lower().endswith((".xml", ".htm")))
    logger.info("DART ZIP(%s) — 문서 파일 %d개", rcept_no, len(doc_files))

    out = []
    for fname in doc_files:
        try:
            raw = zf.read(fname)
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                text = raw.decode("euc-kr", errors="replace")
            out.append((fname, text))
        except Exception as exc:
            logger.debug("HTM 읽기 실패(%s): %s", fname, exc)
    return out


def _find_section_soup(htms: list, keywords: tuple) -> Optional[BeautifulSoup]:
    """htm 텍스트 목록에서 keywords 중 하나를 포함하는 첫 파일을 BeautifulSoup 으로 반환."""
    for fname, text in htms:
        if any(kw in text for kw in keywords):
            logger.info("섹션 발견(%s): %s", keywords[0], fname)
            return BeautifulSoup(text, "lxml")
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

    # 0) 회사명 → corp_code (list.json 은 corp_name 필터 미지원)
    corp_codes = _get_corp_codes(corp_name)
    if not corp_codes:
        logger.warning("DART corp_code 미발견: %s", corp_name)
        return None

    # 1) corp_code 후보별로 공시 목록 검색 (첫 성공 사용)
    items, corp_code = [], ""
    for cc in corp_codes:
        items = _search_disclosures(cc)
        if items:
            corp_code = cc
            break
    if not items:
        logger.warning("DART 공시 없음(최근 120일): %s", corp_name)
        return None

    target = _find_best_disclosure(items)
    if not target:
        return None

    rcept_no = target["rcept_no"]
    logger.info("DART 대상 공시: [%s] %s", rcept_no, target.get("report_nm", ""))

    # 2) ZIP 다운로드 (한 번) → 모든 문서 텍스트 확보
    htms = _download_htm_texts(rcept_no)
    if not htms:
        return None

    # 3) 수요예측 결과 표 파싱 (실패해도 유통가능주식수는 별도로 시도)
    demand = None
    demand_soup = _find_section_soup(htms, _DEMAND_KEYWORDS)
    if demand_soup is not None:
        demand = _parse_demand_table(demand_soup)

    # 4) 공모 후 유통가능주식수 파싱 (주주현황 표 — scraper 로직 재사용)
    #    '발행조건확정' 증권신고서엔 유통가능물량이 없으므로, 없으면 본문 증권신고서를 추가 조회.
    from analyzer import scraper
    circ_soup = _find_section_soup(htms, _CIRC_KEYWORDS)
    if circ_soup is None:
        full = _find_full_registration(items, exclude_rcept=rcept_no)
        if full:
            logger.info("유통가능물량용 본문 증권신고서 조회: [%s] %s",
                        full["rcept_no"], full.get("report_nm", ""))
            circ_soup = _find_section_soup(
                _download_htm_texts(full["rcept_no"]), _CIRC_KEYWORDS)
    circulating = scraper._parse_circulating(circ_soup) if circ_soup is not None else None

    # 수요예측·유통 둘 다 못 얻으면 폴백
    if not demand and not circulating:
        logger.warning("DART 수요예측·유통 모두 미확보: %s", corp_name)
        return None

    result = demand or {"inst_total_demand": None, "lockup_qty": None, "inst_allocation": None}
    result.update({
        "circulating_shares": circulating,
        "corp_code": corp_code,
        "rcept_no": rcept_no,
        "source": "DART",
    })
    logger.info(
        "DART 확보: %s | 총신청=%s | 확약=%s | 배정=%s | 유통=%s",
        corp_name,
        f"{result['inst_total_demand']:,.0f}" if result.get("inst_total_demand") else "-",
        f"{result['lockup_qty']:,.0f}" if result.get("lockup_qty") else "-",
        f"{result['inst_allocation']:,.0f}" if result.get("inst_allocation") else "-",
        f"{circulating:,.0f}" if circulating else "-",
    )
    return result
