"""38커뮤니케이션 크롤링.

세 가지 작업:
  1) fetch_schedule()  : 공모주 청약일정 목록에서 신규 종목의 (종목명, no, 일정) 추출
  2) fetch_detail(no)  : 공모분석 상세 표에서 '원본 수량' 우선 파싱
  3) get_otc_price()   : 장외 팝니다·삽니다 호가 → 이상치 제거 후 평균

HTML 구조 의존을 한곳에 모으기 위해 라벨 기반 조회 헬퍼(_find_value_by_label)를 둔다.
사이트 구조가 바뀌면 라벨 매칭/정규식만 손보면 된다.
"""
import re
import statistics
from typing import Optional

from bs4 import BeautifulSoup

from analyzer import config
from analyzer.net import logger, parse_number, safe_get


# ===========================================================================
# 공통 헬퍼
# ===========================================================================
def _soup(url: str) -> Optional[BeautifulSoup]:
    resp = safe_get(url)
    if resp is None:
        return None
    # resp.text 는 safe_get 에서 EUC-KR 로 디코딩되어 있음
    return BeautifulSoup(resp.text, "lxml")


def _find_value_by_label(soup: BeautifulSoup, *labels: str) -> Optional[str]:
    """표(table)에서 라벨 셀(th/td) 텍스트가 labels 중 하나를 포함하면,
    바로 다음 형제 셀의 텍스트를 반환. 공모분석 표는 '라벨-값' 2열 구조가 많다."""
    for cell in soup.find_all(["th", "td"]):
        cell_text = cell.get_text(strip=True)
        if not cell_text:
            continue
        for label in labels:
            if label in cell_text:
                nxt = cell.find_next_sibling(["td", "th"])
                if nxt is not None:
                    val = nxt.get_text(strip=True)
                    if val:
                        return val
    return None


# ===========================================================================
# 1) 청약일정 목록 → 신규 종목 발견
# ===========================================================================
_NO_RE = re.compile(r"no=(\d+)")
# 공모분석 상세 링크만 인정 (/html/fund/?o=v&no=...). 뉴스(/html/news/) 제외.
_FUND_HREF_RE = re.compile(r"/html/fund/.*?[?&]o=v.*?[?&]no=\d+")
# 청약일 범위: '2026.07.01~07.02' (시작 YYYY.MM.DD ~ 종료 MM.DD)
_SUB_DATE_RE = re.compile(r"(\d{4})\.(\d{1,2})\.(\d{1,2})\s*~\s*(\d{1,2})\.(\d{1,2})")

# 청약 종료 후 이 일수가 지나면 '이미 상장됨'으로 간주하여 목록에서 제외.
# (대부분의 신규상장은 청약 종료 후 2주 이내에 이뤄짐)
LISTING_GRACE_DAYS = 14


def _clean_schedule_name(text: str) -> str:
    """링크 텍스트에서 순수 종목명만 추출.

    예) '피스피스스튜디오, 확정공모가 21,500원' → '피스피스스튜디오'
        '코스모로보틱스(구.엑소아틀레트아시아)'   → 그대로 유지(괄호 안 별칭은 보존)
    - 쉼표 이후 부가 설명(뉴스 제목성 텍스트) 제거
    - '공모청약', '확정공모가' 등 키워드 이후 잘라냄
    """
    name = text.strip()
    # 쉼표 기준 앞부분만 (단, 괄호 안 쉼표는 영향 없음 — 보통 종목명에 쉼표 없음)
    name = name.split(",")[0].strip()
    # 부가 설명 키워드 앞에서 절단
    for kw in ("공모청약", "확정공모가", "공모가", "수요예측", "청약경쟁률", "일정", " 공모"):
        idx = name.find(kw)
        if idx > 0:
            name = name[:idx].strip()
    return name


def _parse_sub_dates(row_text: str):
    """행 텍스트에서 청약 시작·종료 date 추출. 실패 시 (None, None).

    '2026.07.01~07.02' → (date(2026,7,1), date(2026,7,2)).
    종료 월이 시작 월보다 작으면 연말~연초 → 종료 연도 +1.
    """
    import datetime as _dt
    m = _SUB_DATE_RE.search(row_text)
    if not m:
        return None, None
    y, sm, sd, em, ed = (int(g) for g in m.groups())
    try:
        start = _dt.date(y, sm, sd)
        end_year = y + 1 if em < sm else y
        end = _dt.date(end_year, em, ed)
        return start, end
    except ValueError:
        return None, None


def _is_spac(name: str) -> bool:
    """스팩(SPAC) 종목 판정. ('호스팩'도 '스팩' 포함)"""
    return bool(name) and ("스팩" in name or "SPAC" in name.upper())


def _is_reit(name: str) -> bool:
    """리츠(REIT) 종목 판정."""
    return bool(name) and "리츠" in name


def _is_spac_or_reit(name: str) -> bool:
    """스팩 또는 리츠 판정. (scraper 독립 유지를 위한 로컬 헬퍼)"""
    return _is_spac(name) or _is_reit(name)


def fetch_schedule(only_upcoming: bool = True, exclude_spac: bool = True,
                   exclude_reit: bool = True) -> list[dict]:
    """공모주 청약일정 목록을 파싱해 후보 종목 리스트 반환.

    각 항목: {"name", "no", "subscription_date"(str), "sub_start", "sub_end", "listing_date"}
    공모분석 상세 링크(/html/fund/?o=v&no=...)만 종목으로 취급한다.
    뉴스 링크(/html/news/)와 부가 설명 텍스트는 제외/정리한다.

    only_upcoming=True (기본): 이미 상장된 종목을 제외하고
      '청약 예정 + 상장 대기' 종목만 반환한다.
      판정: 청약 종료일 >= 오늘 - LISTING_GRACE_DAYS (청약일 미상이면 안전하게 포함).
    exclude_spac/exclude_reit=True (기본): 각각 스팩·리츠를 목록에서 제외한다.
      스팩 전용 분석을 위해 목록에 스팩을 노출하려면 exclude_spac=False 로 호출.
    """
    from datetime import date, timedelta

    soup = _soup(config.SCHEDULE_LIST_URL)
    if soup is None:
        logger.error("청약일정 목록 로드 실패")
        return []

    today = date.today()
    cutoff = today - timedelta(days=LISTING_GRACE_DAYS)

    candidates: dict[str, dict] = {}  # no -> record (중복 제거)
    dropped_excluded = 0
    for link in soup.find_all("a", href=True):
        href = link["href"]
        # 공모분석(fund) 상세 링크만 — 뉴스 링크 제외
        if not _FUND_HREF_RE.search(href):
            continue
        m = _NO_RE.search(href)
        if not m:
            continue
        raw_name = link.get_text(strip=True)
        if not raw_name:
            continue
        name = _clean_schedule_name(raw_name)
        if not name:
            continue
        # 스팩/리츠 제외 (각각 토글 — 스팩 분석용으로 스팩만 노출 가능)
        if (exclude_spac and _is_spac(name)) or (exclude_reit and _is_reit(name)):
            dropped_excluded += 1
            continue
        no = m.group(1)
        if no in candidates:
            continue

        # 종목 링크의 부모 행에서 청약일 추출
        tr = link.find_parent("tr")
        row_text = tr.get_text(" ", strip=True) if tr else ""
        sub_start, sub_end = _parse_sub_dates(row_text)

        candidates[no] = {
            "no": no,
            "name": name,
            "subscription_date": (f"{sub_start}~{sub_end}" if sub_start and sub_end else None),
            "sub_start": sub_start,
            "sub_end": sub_end,
            "listing_date": None,
        }

    result = list(candidates.values())
    total = len(result)

    spac_note = f", 스팩/리츠 {dropped_excluded}종목 제외" if dropped_excluded else ""

    if only_upcoming:
        kept = []
        dropped = 0
        for c in result:
            se = c.get("sub_end")
            # 청약일 미상 → 안전하게 포함 / 청약 종료일이 cutoff 이후면 미상장으로 간주
            if se is None or se >= cutoff:
                kept.append(c)
            else:
                dropped += 1
        logger.info("청약일정 후보 %d종목 (미상장 %d, 이미 상장 추정 %d 제외%s)",
                    total, len(kept), dropped, spac_note)
        return kept

    logger.info("청약일정에서 후보 %d종목 발견%s", total, spac_note)
    return result


# ===========================================================================
# 2) 공모분석 상세 → 원본 수량 우선 파싱
# ===========================================================================
def _parse_alloc_max(text: Optional[str]) -> Optional[float]:
    """'1,080,000~1,160,000 주' 같은 배정물량 문자열에서 최대값(최종 배정) 반환.
    범위가 아니면 그 값을, 숫자가 없으면 None."""
    if not text:
        return None
    nums = [parse_number(t) for t in re.findall(r"[\d,]+", text)]
    nums = [n for n in nums if n and n > 0]
    return max(nums) if nums else None


def fetch_detail(no: str) -> Optional[dict]:
    """상세 페이지 파싱. 원본 수량(분자/분모)을 우선 확보, 실패 시 표시 %로 폴백.

    반환 dict 주요 키:
      name, no, listing_date, confirmed_price, face_value, underwriter,
      inst_allocation(기관 배정물량), inst_total_demand(기관 총 신청수량),
      lockup_qty(15일~6개월 확약 수량 합계), circulating_shares(유통가능주식수),
      band_high(희망밴드 상단), raw_verified(bool),
      fallback_competition(%, raw 실패시), fallback_lockup(%, raw 실패시)
    필수값(종목명/확정공모가) 부재 시 "공시 대기" 로깅 후 None.
    """
    url = config.BASE_DETAIL_URL.format(no=no)
    soup = _soup(url)
    if soup is None:
        return None

    try:
        name = _find_value_by_label(soup, "종목명") or ""
        name = name.strip()
        confirmed_price = parse_number(_find_value_by_label(soup, "확정공모가", "공모가격"))

        if not name or confirmed_price is None:
            logger.info("[공시 대기] no=%s 종목명/확정공모가 미공개 → 스킵", no)
            return None

        face_value = parse_number(_find_value_by_label(soup, "액면가"))
        listing_date = _normalize_date(
            _find_value_by_label(soup, "신규상장일", "상장일"))
        underwriter = _find_value_by_label(soup, "주간사", "주관사", "대표주관") or "-"

        # 희망공모가 밴드 상단·하단 모두 파싱 (확정공모가 위치 판단용)
        band_raw = _find_value_by_label(soup, "희망공모가액", "희망공모가", "희망공모가밴드") or ""
        band_high, band_low = _parse_band(band_raw)

        # --- 원본 수량 (분자/분모) ---
        # [버그수정] "기관투자자등" 추가 (실제 라벨)
        # 기관 배정물량 — '1,080,000~1,160,000 주'처럼 범위면 최종 배정(상한)을 사용.
        # 사이트가 표시하는 기관경쟁률도 상한(최종 배정) 기준이므로 일치한다.
        inst_allocation = _parse_alloc_max(
            _find_value_by_label(soup, "기관투자자등", "기관배정", "기관 배정"))
        # 수요예측 결과 표에서 기관 총 신청수량 전용 파서 우선 시도
        inst_total_demand = _parse_inst_demand(soup)
        # 유통가능주식수 전용 파서 우선 시도
        circulating_shares = _parse_circulating(soup)
        lockup_qty = _sum_lockup_quantity(soup)

        raw_verified = all(v is not None for v in (
            inst_allocation, inst_total_demand, circulating_shares, lockup_qty))

        # 주관사별 최소 청약 수량 파싱 (증거금 계산용)
        min_qty_map = _parse_min_qty(soup, underwriter)

        # 장외 매도·매수 가격 (상세 페이지 내 팝니다/삽니다 섹션)
        sell_prices, buy_prices = _parse_otc_from_detail(soup, confirmed_price)

        record = {
            "no": no,
            "name": name,
            "listing_date": listing_date,
            "confirmed_price": confirmed_price,
            "face_value": face_value,
            "underwriter": underwriter,
            "band_high": band_high,
            "band_low": band_low,
            "inst_allocation": inst_allocation,
            "inst_total_demand": inst_total_demand,
            "lockup_qty": lockup_qty,
            "circulating_shares": circulating_shares,
            "raw_verified": raw_verified,
            "fallback_competition": None,
            "fallback_lockup": None,
            "min_qty_map": min_qty_map,
            "sell_prices": sell_prices,   # 팝니다 가격 목록
            "buy_prices": buy_prices,     # 삽니다 가격 목록
        }

        if not raw_verified:
            # [버그수정] "경쟁률" 라벨 제거 → "청약경쟁률" 오매칭 방지. "기관경쟁률"만 사용.
            record["fallback_competition"] = parse_number(
                _find_value_by_label(soup, "기관경쟁률"))
            record["fallback_lockup"] = parse_number(
                _find_value_by_label(soup, "의무보유확약", "확약비율"))
            logger.warning("[RAW_UNVERIFIED] %s: 원본 수량 일부 미파싱 → 표시 %% 폴백 사용", name)

        return record

    except Exception as exc:  # 파싱 중 예기치 못한 구조 변화
        logger.exception("[공시 대기] no=%s 상세 파싱 예외: %s", no, exc)
        return None


_MIN_QTY_RE = re.compile(r"(?:최소|기본)\s*청약\s*(?:수량|단위|한도)[^\d]*(\d+)\s*주")
_MIN_QTY_RE2 = re.compile(r"청약\s*(?:최소|기본)\s*단위\s*[:\s]+(\d+)\s*주")
_DEFAULT_MIN_QTY = 10  # 한국 공모주 업계 표준 최소 청약 단위


def _parse_min_qty(soup: BeautifulSoup, underwriter: str) -> dict:
    """주관사별 최소 청약 수량 파싱.

    38커뮤니케이션 페이지는 '최저: - 주'로 명시하지 않는 경우가 대부분이므로
    업계 표준 10주를 기본값(estimated=True)으로 사용한다.
    페이지에 "최소 청약 수량 X주" 형태가 명시되어 있으면 해당 값을 사용(estimated=False).

    반환: {"NH투자증권": {"min_qty": 10, "estimated": True}, ...}
    """
    names = [n.strip() for n in underwriter.split(",") if n.strip() and n.strip() != "-"]
    if not names:
        return {}

    # 페이지 전체 텍스트에서 명시적 최소 청약 수량 탐색
    page_text = soup.get_text(" ", strip=True)
    explicit_min = None
    for pattern in (_MIN_QTY_RE, _MIN_QTY_RE2):
        m = pattern.search(page_text)
        if m:
            n = int(m.group(1))
            if 1 <= n <= 1000:
                explicit_min = n
                break

    return {
        name: {"min_qty": explicit_min or _DEFAULT_MIN_QTY,
               "estimated": explicit_min is None}
        for name in names
    }


def _parse_band(text: str) -> tuple:
    """'19,000 ~ 21,500 원' 형태에서 (band_high, band_low) 반환.
    숫자를 모두 추출해 큰 값=상단, 작은 값=하단으로 처리. 파싱 실패 시 (None, None).
    """
    nums = [parse_number(t) for t in re.findall(r"[\d,]+", text)]
    nums = [n for n in nums if n and n > 0]
    if not nums:
        return None, None
    return max(nums), min(nums)


_OTC_DATE_RE = re.compile(r"\d{1,2}/\d{1,2}\s+\d{1,2}:\d{2}")  # '05/29 10:51'


def _parse_otc_from_detail(soup: BeautifulSoup,
                           confirmed_price: Optional[float]) -> tuple:
    """상세 페이지 내 '팝니다(가격참고)' / '삽니다(가격참고)' 섹션에서
    매도·매수 희망가격을 추출. OTC 별도 URL 불필요.

    반환: (sell_prices: list[float], buy_prices: list[float])

    실제 데이터 행 구조: [종목명 | 희망가격 | 수량 | 날짜('05/29 10:51')]
    - 헤더는 '팝니다 (가격참고)'/'삽니다 (가격참고)'가 셀 '맨 앞'에 오는 짧은 행만 인정
      (전체 텍스트를 담은 중첩 wrapper TR 오인 방지)
    - 데이터 행은 마지막 셀이 날짜 형식(MM/DD HH:MM)이어야 인정
      (매출액·순이익 등 재무 수치 오수집 방지)
    """
    sell_prices: list[float] = []
    buy_prices: list[float] = []

    # 공모가 대비 합리적 범위 필터 (10%~1000%)
    min_p = (confirmed_price or 1) * 0.10
    max_p = (confirmed_price or float("inf")) * 10.0

    mode = None   # "sell" | "buy" | None
    for row in soup.find_all("tr"):
        cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
        if not cells:
            continue

        first = cells[0]

        # ── 섹션 헤더 감지: 첫 셀이 '팝니다/삽니다 (가격참고)'이고 짧은 행만 ──
        if first.startswith("팝니다") and "가격참고" in first and len(cells) <= 6:
            mode = "sell"
            continue
        if first.startswith("삽니다") and "가격참고" in first and len(cells) <= 6:
            mode = "buy"
            continue

        if mode is None:
            continue

        # ── 데이터 행 검증: 4칸 + 마지막 칸 날짜 형식 ──
        if len(cells) < 4:
            continue
        if not _OTC_DATE_RE.search(cells[-1]):
            continue   # 날짜 없는 행 = 재무 데이터 등 → 스킵

        price = parse_number(cells[1])   # 희망가격 = 두 번째 셀
        if price and min_p <= price <= max_p:
            # 이상치 제거를 위해 상위 5개로 자르지 않고 넉넉히(최대 30건) 수집한다.
            # 실제 평균에 쓰는 '상위 5개'는 get_otc_price 에서 이상치 제외 후 선별.
            if mode == "sell" and len(sell_prices) < _OTC_COLLECT_MAX:
                sell_prices.append(price)
            elif mode == "buy" and len(buy_prices) < _OTC_COLLECT_MAX:
                buy_prices.append(price)

        if len(sell_prices) >= _OTC_COLLECT_MAX and len(buy_prices) >= _OTC_COLLECT_MAX:
            break

    logger.info("장외 수집(상세페이지): 팝니다 %d건%s | 삽니다 %d건%s",
                len(sell_prices),
                f" {[round(p) for p in sell_prices]}" if sell_prices else "",
                len(buy_prices),
                f" {[round(p) for p in buy_prices]}" if buy_prices else "")
    return sell_prices, buy_prices


def _normalize_date(text: Optional[str]) -> Optional[str]:
    """'2025.11.25', '2025-11-25', '2025/11/25 (화)' 등을 'YYYY-MM-DD'로 정규화."""
    if not text:
        return None
    m = re.search(r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})", text)
    if not m:
        return None
    y, mo, d = m.groups()
    return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"


def _sum_lockup_quantity(soup: BeautifulSoup) -> Optional[float]:
    """수요예측 확약 신청 현황 표에서 15일~6개월 확약 수량 합계 추출.

    [버그 수정 내역]
    - 구 버전: "6개월" 검색 → 주주현황 표의 "2년 6개월" 행도 매칭, 주주 보유수량 오합산
    - 구 버전: parse_number("6개월 확약") = 6.0 → 실제 확약수량 대신 기간 숫자를 합산
    [수정] "X개월 확약" / "15일 확약" 전체 문자열 매칭 + 전용 테이블 한정 + 최소 1만주 이상
    """
    # 확약 기간 전체 문자열 — "2년 6개월"과 구분하기 위해 " 확약" 포함
    exact_periods = ("15일 확약", "1개월 확약", "3개월 확약", "6개월 확약")

    # 전용 확약 테이블 탐색: "신청수량" AND 확약기간 포함, "주주명" 미포함
    for table in soup.find_all("table"):
        ttext = table.get_text(" ", strip=True)
        if "신청수량" not in ttext:
            continue
        if not any(k in ttext for k in exact_periods):
            continue
        if "주주명" in ttext:   # 주주현황 표는 제외 (확약 기간 혼재)
            continue

        total = 0.0
        found = False
        for row in table.find_all("tr"):
            row_text = row.get_text(" ", strip=True)
            if not any(k in row_text for k in exact_periods):
                continue
            if "합계" in row_text or "소계" in row_text:
                continue
            for c in row.find_all("td"):
                n = parse_number(c.get_text(strip=True))
                # 최소 10,000주 이상 (기간 숫자 "6", "3", "1", "15" 배제)
                if n is not None and n >= 10_000:
                    total += n
                    found = True
                    break

        if found:
            return total

    return None


# 기관 단순경쟁 비율 셀 (예: '1,294.99:1') — 셀 전체가 비율 형태일 때만 매칭
_COMP_RATIO_RE = re.compile(r"^[\d,]+(?:\.\d+)?\s*:\s*1$")


def _parse_inst_demand(soup: BeautifulSoup) -> Optional[float]:
    """수요예측 결과 표에서 기관 총 신청수량(주) 추출.

    실제 페이지 구조(38커뮤니케이션) — '단순경쟁' 데이터행:
      참여건수 | 신청주식수      | 단순경쟁률
      2,252    | 1,502,187,765   | 1,294.99:1

    [버그 수정] 38 상세 페이지는 전체 내용을 하나의 거대 셀에 담은 wrapper 표가
    먼저 잡혀, 문서상 앞서 나오는 확약수량(예: '3개월 확약 180,918,700')을
    총 신청수량으로 오인하는 문제가 있었다.
    → '단순경쟁률(…:1)' 셀이 들어있는 '짧은 데이터행'만 인정하고, 그 행의
      1억 이상 숫자를 총 신청수량으로 반환한다(거대 wrapper 행 자동 배제).
    """
    for row in soup.find_all("tr"):
        cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
        cells = [c for c in cells if c]
        if not (2 <= len(cells) <= 6):   # 데이터행만 (거대 wrapper 행 배제)
            continue
        if not any(_COMP_RATIO_RE.match(c) for c in cells):
            continue   # 단순경쟁률(…:1) 셀이 있는 행만
        for c in cells:
            n = parse_number(c)
            if n is not None and n >= 100_000_000:   # 1억 이상 = 총 신청수량
                return n
    return None


def _circ_pair_in_cells(cells: list) -> Optional[float]:
    """셀 텍스트 리스트에서 (大숫자A)(X%)(大숫자B)(Y%) 패턴 중
    두 비율 합이 ~100% 인 쌍을 찾아 두 번째 값(유통가능주식수)을 반환.
    (매각제한물량% + 유통가능물량% = 100)
    """
    for i in range(len(cells) - 3):
        n1 = parse_number(cells[i])
        n2 = parse_number(cells[i + 2])
        t1, t2 = cells[i + 1], cells[i + 3]
        if not (n1 and n2 and "%" in t1 and "%" in t2):
            continue
        # 유효 주식수 범위 체크 (재무제표 대형 수치 배제)
        if not (100_000 <= n1 <= 100_000_000 and 100_000 <= n2 <= 100_000_000):
            continue
        p1 = parse_number(t1)
        p2 = parse_number(t2)
        if not (p1 and p2):
            continue
        if 99 <= p1 + p2 <= 101:
            return n2   # 두 번째 값 = 유통가능주식수
    return None


def _parse_circulating(soup: BeautifulSoup) -> Optional[float]:
    """주주현황 표에서 공모 후 유통가능주식수(합계) 추출.

    [버그 수정 내역]
    - 외부 래퍼 테이블의 컬럼 인덱스가 재무제표 수치를 가리켜 오파싱 → 셀 패턴 탐색으로 전환
    - 셀 전체를 순차 탐색하면 '소계' 행의 (공모전 지분율 + 공모후 지분율)이 우연히
      ~100% 가 되어 조기 오매칭(예: 스트라드비전 최대주주 53.65%+46.45%=100.1%).
    [수정] **합계 행을 우선** 탐색해 그 안에서만 (매각제한% + 유통%)=100 쌍을 찾는다.
      합계 행이 없을 때만 표 전체를 폴백 탐색(이때는 마지막=합계에 가까운 쌍 우선).

    대상 테이블: "유통가능물량" + ("주주명" 또는 "성명") 포함 (주주현황 표)
      ※ 재상장·이전상장 종목은 라벨이 "성명"인 경우가 있어 둘 다 허용한다.
      ※ 38은 라벨을 "성 명"·"구 분"처럼 공백을 넣어 정렬하는 경우가 있어(예: 레메디),
        라벨 비교 전에 공백을 제거한다(공백 무시 매칭).
    유효 범위: 유통가능주식수 = 100,000 ~ 100,000,000 주
    """
    for table in soup.find_all("table"):
        ttext_ns = table.get_text(" ", strip=True).replace(" ", "")
        if "유통가능물량" not in ttext_ns:
            continue
        if "주주명" not in ttext_ns and "성명" not in ttext_ns:
            continue

        # 1순위: '합계' 행에서만 탐색 (소계 오매칭 방지)
        for row in table.find_all("tr"):
            cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
            cells = [c for c in cells if c]
            if cells and cells[0].replace(" ", "").startswith("합계"):
                v = _circ_pair_in_cells(cells)
                if v is not None:
                    return v

        # 2순위(폴백): 표 전체 셀 — 마지막(=합계에 가까운) 매칭을 우선
        all_cells = [c.get_text(strip=True) for c in table.find_all(["td", "th"])]
        last = None
        for i in range(len(all_cells) - 3):
            v = _circ_pair_in_cells(all_cells[i:i + 4])
            if v is not None:
                last = v
        if last is not None:
            return last

    return None


# ===========================================================================
# 3) 장외 가격 → 이상치 제거 후 평균 (방어 로직 강화)
# ===========================================================================

# 장외 시세 없음을 나타내는 사이트 텍스트 패턴
_NO_PRICE_TEXTS = ("시세없음", "등록된 글이 없", "데이터가 없", "검색결과가 없")

_PRICE_RE = re.compile(r"\d{1,3}(?:,\d{3})+|\d{4,}")

_OTC_TOP_N = 5            # 평균에 사용할 정상 호가 상위 개수(매도·매수 각각)
_OTC_COLLECT_MAX = 30     # 수집 단계 상한(이상치 제거 후 상위 N개를 뽑기 위해 넉넉히 모음)


def _otc_band(prices: list, tol: float = config.OTC_OUTLIER_TOL) -> tuple:
    """중앙값(median) 기준 허용 밴드 (low, high) 반환.

    장외 게시판에는 시세와 동떨어진 호가가 섞인다(예: 대부분 5~6만인데
    갑자기 10만 매도호가, 2만 헐값 매수호가). 중앙값은 극단값에 둔감하므로
    중앙값 대비 ±tol(기본 40%) 밴드를 기준으로 삼는다.
      예) 중앙값 5.5만 → (3.3만, 7.7만). 10만(+82%)·2만(-64%) 모두 밴드 밖.

    데이터 3개 미만이면 신뢰할 중앙값을 못 잡아 (None, None) 반환(필터 안 함).
    """
    valid = [p for p in prices if p is not None and p > 0]
    if len(valid) < 3:
        return None, None
    med = statistics.median(valid)
    if med <= 0:
        return None, None
    return med * (1 - tol), med * (1 + tol)


def _reject_otc_outliers(prices: list, tol: float = config.OTC_OUTLIER_TOL) -> list:
    """중앙값 밴드를 벗어난 터무니없는 호가를 제거한 리스트 반환.

    데이터 3개 미만이면 원본 유지(0·None 만 정리). 필터 결과가 비면 원본 반환.
    """
    valid = [p for p in prices if p is not None and p > 0]
    low, high = _otc_band(valid, tol)
    if low is None:
        return valid
    kept = [p for p in valid if low <= p <= high]
    return kept or valid


def get_otc_price(
    name: str,
    face_value: Optional[float] = None,  # 호환 유지 (미사용)
    confirmed_price: Optional[float] = None,
    sell_prices: Optional[list] = None,
    buy_prices: Optional[list] = None,
) -> Optional[float]:
    """장외 시세가 산출. 없으면 None(=장외 시세 없음).

    장외 '있음' 판정 기준은 **팝니다(매도호가)와 삽니다(매수호가)가 모두 존재**하는
    것이다. 한쪽만 있으면 실거래 시세로 보기 어려워 '없음'으로 처리한다.
      (예: 져스텍 — 삽니다만 5건, 팝니다 0건 → 장외 없음)

    양쪽이 모두 있으면 매도·매수 호가를 합쳐 이상치 제거 후 평균.
    이상치 제거: 중앙값 대비 ±OTC_OUTLIER_TOL 밴드 밖 호가는 버린다.

    반환:
      float  — 장외 시세 있음(평균가)
      None   — 장외 시세 없음(매도/매수호가 중 하나라도 없음 / 데이터 미확보 / 예외)
               → 점수 -2 대상
    """
    try:
        sells = list(sell_prices or [])
        buys = list(buy_prices or [])

        # 상세 페이지에 팝니다·삽니다가 모두 없을 때만 OTC URL 재시도
        if not sells and not buys:
            url = config.OTC_URL.format(name=name)
            soup = _soup(url)
            if soup is not None:
                page_text = soup.get_text(" ", strip=True)
                if not any(kw in page_text for kw in _NO_PRICE_TEXTS):
                    sells, buys = _parse_otc_from_detail(soup, confirmed_price)

        # 매도호가·매수호가 둘 중 하나라도 없으면 장외 시세 없음으로 판정
        if not sells or not buys:
            logger.info("장외 없음(매도 %d건·매수 %d건 — 양쪽 모두 필요): %s",
                        len(sells), len(buys), name)
            return None

        raw_n = len(sells) + len(buys)

        # ── 1단계: 터무니없는 호가(이상치)를 먼저 제외 ──────────────────────
        # 중앙값 밴드를 매도+매수 전체 분포에서 산출한 뒤, 각 호가를 거른다.
        # (상위 5개를 '자른 뒤' 거르는 게 아니라, 거른 뒤 상위 5개를 뽑는다)
        low, high = _otc_band(sells + buys)
        if low is not None:
            sells = [p for p in sells if low <= p <= high]
            buys = [p for p in buys if low <= p <= high]

        # 이상치 제거 후에도 양쪽이 모두 남아야 장외 시세로 인정
        if not sells or not buys:
            logger.info("장외 없음(이상치 제외 후 매도 %d·매수 %d): %s",
                        len(sells), len(buys), name)
            return None

        # ── 2단계: 정상 호가 중 상위 5개씩(게시판 상단=최신) → 통합 평균 ──────
        chosen = sells[:_OTC_TOP_N] + buys[:_OTC_TOP_N]
        otc = sum(chosen) / len(chosen)

        logger.info(
            "장외 평균(%s): %s원 (수집 %d건 → 이상치 제외 후 매도 %d·매수 %d 중 상위 %d개 사용)",
            name, f"{round(otc):,}", raw_n, len(sells), len(buys), len(chosen),
        )
        return otc

    except Exception as exc:
        logger.warning("장외 가격 파싱 예외(%s): %s → 장외 없음 처리", name, exc)
        return None


def _extract_price_from_row(row) -> Optional[float]:
    """게시판 한 행에서 호가(원)로 보이는 첫 숫자(1,000 이상)를 추출.
    정규식 실패 시 None 반환(크래시 없음).
    """
    try:
        for cell in row.find_all("td"):
            text = cell.get_text(strip=True)
            if not text:
                continue
            m = _PRICE_RE.search(text)
            if m:
                val = parse_number(m.group(0))
                if val is not None and val >= 1000:   # 수량·번호 같은 작은 수 배제
                    return val
    except Exception:
        pass
    return None
