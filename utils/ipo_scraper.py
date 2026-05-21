import re
import warnings
from datetime import date

import requests

try:
    from bs4 import BeautifulSoup
    _BS4_AVAILABLE = True
except ImportError:
    _BS4_AVAILABLE = False

_URL_IPO04 = "http://www.ipostock.co.kr/sub03/ipo04.asp"
_URL_IPO02 = "http://www.ipostock.co.kr/sub03/ipo02.asp"

_DATE_PAT = re.compile(r"\d{2}\.\d{2}\s*~\s*\d{2}\.\d{2}")

_BROKERS = [
    "미래에셋증권", "NH투자증권", "한국투자증권", "삼성증권",
    "KB증권", "신한투자증권", "하나증권", "메리츠증권",
    "키움증권", "대신증권", "교보증권", "현대차증권",
    "신영증권", "한화투자증권", "DB금융투자", "SK증권",
    "이베스트투자증권", "유진투자증권", "IBK투자증권", "BNK투자증권",
    "다올투자증권", "카카오페이증권", "토스증권", "흥국증권",
    "케이프투자증권", "상상인증권", "코리아에셋투자증권", "한국포스증권",
    "우리투자증권",
]


def _fetch_soup(url: str):
    if not _BS4_AVAILABLE:
        return None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            resp = requests.get(url, verify=False, timeout=10)
        html = resp.content.decode("utf-8", errors="replace")
        return BeautifulSoup(html, "html.parser")
    except Exception:
        return None


def _find_ipo_rows(soup) -> list:
    rows = []
    for tr in soup.find_all("tr"):
        cells = tr.find_all("td")
        if len(cells) < 2:
            continue
        if _DATE_PAT.search(cells[1].get_text(strip=True)):
            rows.append(tr)
    return rows


def _parse_mmdd(mmdd: str, ref_year: int) -> date | None:
    mmdd = mmdd.strip()
    m = re.match(r"(\d{1,2})\.(\d{2})", mmdd)
    if not m:
        return None
    month, day = int(m.group(1)), int(m.group(2))
    try:
        d = date(ref_year, month, day)
    except ValueError:
        return None
    # IPO 사이트는 미래 일정만 표시 — 60일 이상 과거면 내년 날짜로 처리
    from datetime import timedelta
    if d < date.today() - timedelta(days=60):
        try:
            d = date(ref_year + 1, month, day)
        except ValueError:
            pass
    return d


def _parse_price(price_str: str) -> int | None:
    nums = re.findall(r"[\d,]+", price_str)
    if not nums:
        return None
    try:
        val = int(nums[-1].replace(",", ""))
        return val if val > 0 else None
    except ValueError:
        return None


def _match_broker(raw: str) -> str | None:
    raw = raw.strip()
    for b in _BROKERS:
        if b in raw or raw in b:
            return b
    return None


def _search_ipo04(name_lower: str, year: int) -> dict | None:
    soup = _fetch_soup(_URL_IPO04)
    if soup is None:
        return None
    for tr in _find_ipo_rows(soup):
        cells = tr.find_all("td")
        if len(cells) < 10:
            continue
        stock = cells[2].get_text(strip=True)
        if name_lower not in stock.lower():
            continue
        date_range = cells[1].get_text(strip=True)
        parts = date_range.split("~")
        if len(parts) != 2:
            continue
        confirmed = _parse_price(cells[4].get_text(strip=True))
        hope = _parse_price(cells[3].get_text(strip=True))
        return {
            "sub_start":    _parse_mmdd(parts[0], year),
            "sub_end":      _parse_mmdd(parts[1], year),
            "listing_date": _parse_mmdd(cells[7].get_text(strip=True), year),
            "ipo_price":    confirmed if confirmed and confirmed > 0 else hope,
            "broker":       _match_broker(cells[9].get_text(strip=True)),
        }
    return None


def _search_ipo02(name_lower: str, year: int) -> dict | None:
    soup = _fetch_soup(_URL_IPO02)
    if soup is None:
        return None
    for tr in _find_ipo_rows(soup):
        cells = tr.find_all("td")
        if len(cells) < 10:
            continue
        stock = cells[2].get_text(strip=True)
        if name_lower not in stock.lower():
            continue
        date_range = cells[1].get_text(strip=True)
        parts = date_range.split("~")
        if len(parts) != 2:
            continue
        return {
            "sub_start":    _parse_mmdd(parts[0], year),
            "sub_end":      _parse_mmdd(parts[1], year),
            "listing_date": _parse_mmdd(cells[8].get_text(strip=True), year),
            "ipo_price":    _parse_price(cells[5].get_text(strip=True)),
            "broker":       _match_broker(cells[9].get_text(strip=True)),
        }
    return None


def search_ipo_on_ipostock(stock_name: str) -> dict | None:
    """
    종목명(부분 일치)으로 ipostock.co.kr 검색.
    1) ipo04.asp(공모청약일정) — 확정 공모가 우선
    2) ipo02.asp(수요예측일정) — 희망가 상한 fallback
    실패 시 None 반환 (예외 없음).
    """
    if not _BS4_AVAILABLE:
        return None
    if not stock_name.strip():
        return None
    name_lower = stock_name.strip().lower()
    year = date.today().year
    result = _search_ipo04(name_lower, year)
    if result is None:
        result = _search_ipo02(name_lower, year)
    return result
