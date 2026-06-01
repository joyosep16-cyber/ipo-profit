"""공모주 분석 페이지 — 수요예측 점수 분석 (analyzer 엔진).

청약일정 목록에서 종목을 고르거나 직접 검색하여,
기관 경쟁률·의무보유확약·유통가능규모·장외 괴리율·증거금을 분석하고
가이드 스코어링(총점/추천 등급)을 카드로 표시한다.
스팩/리츠는 점수 산정에서 제외하고 안내만 표시한다.
"""
from datetime import date, datetime

import streamlit as st

from database import add_watchlist_item, get_setting
from utils.constants import WATCHLIST_STATUS_INTERESTED
from utils import discord_notifier
from analyzer import scraper, service

st.title("🔍 공모주 분석")
st.caption("38커뮤니케이션 수요예측 결과 + DART 교차검증 기반 점수 분석")


# DART 키를 DB 설정에서 환경변수로 주입 (analyzer.config.get_dart_api_key 가 읽음)
import os
_dart_key = get_setting("DART_API_KEY", "")
if _dart_key:
    os.environ["DART_API_KEY"] = _dart_key


@st.cache_data(ttl=1800, show_spinner=False)
def _cached_schedule() -> list[dict]:
    return scraper.fetch_schedule()


@st.cache_data(ttl=1800, show_spinner=False)
def _cached_analyze(no: str) -> dict | None:
    return service.analyze_by_no(no)


def _parse_date(s):
    """'YYYY-MM-DD' 문자열 → date. 실패 시 None."""
    if not s:
        return None
    try:
        return datetime.strptime(str(s), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _render_score_card(bundle: dict) -> None:
    merged = bundle["merged"]
    metrics = bundle["metrics"]
    result = bundle["result"]
    is_spac = bundle["is_spac"]
    name = bundle["name"]

    # 스팩/리츠는 분석 대상에서 아예 제외 — 안내만 표시
    if is_spac:
        st.info(f"ℹ️ **{name}** 은(는) 스팩(SPAC)/리츠(REIT) 종목으로 "
                f"공모주 점수 분석 대상에서 제외됩니다.")
        return

    raw_warn = "" if metrics.get("raw_verified") else " ⚠️추정"

    # 헤더
    st.subheader(f"📊 {name}")

    # 공모가 / 밴드
    price = merged.get("confirmed_price")
    band_low, band_high = merged.get("band_low"), merged.get("band_high")
    band_str = "-"
    if band_low and band_high and band_low != band_high:
        band_str = f"{int(band_low):,} ~ {int(band_high):,}원"
    elif band_high:
        band_str = f"{int(band_high):,}원"

    c1, c2, c3 = st.columns(3)
    c1.metric("확정 공모가", f"{int(price):,}원" if price else "-")
    c2.metric("희망 공모가", band_str)
    c3.metric("상장 예정일", str(merged.get("listing_date") or "-"))

    st.divider()

    # 핵심 지표
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("기관 경쟁률", f"{metrics['inst_competition']:,.2f} : 1{raw_warn}")
    m2.metric("의무보유확약", f"{metrics['lockup_ratio']:.2f}%{raw_warn}")
    if is_spac:
        m3.metric("유통가능규모", "N/A")
        m4.metric("장외 괴리율", "N/A")
    else:
        m3.metric("유통가능규모", f"{metrics['circulating_eok']:,.0f}억원")
        prem = metrics["otc_premium"]
        m4.metric("장외 괴리율", f"{prem:+.2f}%" if prem is not None else "N/A")

    # 데이터 신뢰도
    if merged.get("data_quality"):
        st.caption(f"데이터 신뢰도: {merged['data_quality']}  ·  주관사: {merged.get('underwriter','-')}")

    # 증거금
    deposit_map = metrics.get("deposit_map") or {}
    if deposit_map:
        lines = []
        for bname, info in deposit_map.items():
            qty = info.get("min_qty", 10)
            dep = info.get("deposit", 0)
            est = " 추정" if info.get("estimated", True) else ""
            lines.append(f"🏢 **{bname}** — 최소 {qty}주{est} / 증거금 **{dep:,}원**")
        st.markdown("**주관사별 최소 증거금**\n\n" + "\n\n".join(lines))

    st.divider()

    # 점수 / 추천
    if is_spac:
        st.info(f"ℹ️ {result['notice']}")
    else:
        total = result["total"]
        grade = result["grade"]
        verdict = result["verdict"]
        if total >= 16:
            st.success(f"🎯 총점 **{total}점** · {grade} · **{verdict}**\n\n💡 {result['action']}")
        elif total >= 10:
            st.warning(f"🎯 총점 **{total}점** · {grade} · {verdict}\n\n💡 {result['action']}")
        else:
            st.error(f"🎯 총점 **{total}점** · {grade} · {verdict}\n\n💡 {result['action']}")

    # 액션 버튼
    b1, b2 = st.columns(2)
    with b1:
        if st.button("💬 Discord 발송", key=f"disc_{bundle['no']}", use_container_width=True):
            if not (os.getenv("DISCORD_WEBHOOK_URL") or get_setting("DISCORD_WEBHOOK_URL")):
                st.error("Discord 웹훅이 설정되지 않았습니다. 설정 페이지에서 등록하세요.")
            else:
                discord_notifier.send_analysis_score(merged, result, metrics)
                st.success("Discord로 발송했습니다.")
    with b2:
        if st.button("⭐ 관심목록에 추가", key=f"wl_{bundle['no']}", use_container_width=True):
            broker = (merged.get("underwriter") or "").split(",")[0].strip() or None
            add_watchlist_item({
                "stock_name": name,
                "broker": broker,
                "listing_date": _parse_date(merged.get("listing_date")),
                "ipo_price": int(price) if price else None,
                "memo": "",
                "status": WATCHLIST_STATUS_INTERESTED,
                "analysis_score": result.get("total"),
                "analysis_grade": result.get("grade"),
                "data_quality": merged.get("data_quality"),
                "otc_premium": metrics.get("otc_premium"),
                "analyzed_at": datetime.now(),
            })
            st.success(f"'{name}' 을(를) 관심목록에 추가했습니다. (점수 {result.get('total')})")


# ============================================================================
# 탭 구성
# ============================================================================
tab_list, tab_search = st.tabs(["📅 청약일정 목록", "🔎 직접 검색"])

with tab_list:
    cols = st.columns([3, 1])
    with cols[1]:
        if st.button("🔄 목록 새로고침", use_container_width=True):
            _cached_schedule.clear()
    candidates = _cached_schedule()
    if not candidates:
        st.warning("청약일정을 불러오지 못했습니다. (네트워크 또는 사이트 상태 확인)")
    else:
        names = [f"{c['name']}  (no={c['no']})" for c in candidates]
        idx = st.selectbox("분석할 종목 선택", range(len(candidates)),
                           format_func=lambda i: names[i])
        if st.button("📊 분석 실행", type="primary"):
            with st.spinner("분석 중... (크롤링·DART 조회로 수 초 소요)"):
                bundle = _cached_analyze(candidates[idx]["no"])
            if bundle:
                _render_score_card(bundle)
            else:
                st.error("분석 실패 — 공시 대기 종목이거나 데이터가 아직 없습니다.")

with tab_search:
    mode = st.radio("검색 방식", ["종목명", "고유번호(no)"], horizontal=True)
    query = st.text_input("입력", placeholder="예) 피스피스스튜디오  또는  2287")
    if st.button("🔎 검색·분석", type="primary", key="search_btn") and query.strip():
        with st.spinner("분석 중..."):
            if mode == "고유번호(no)":
                bundle = _cached_analyze(query.strip())
            else:
                no = service.find_no_by_name(query.strip())
                bundle = _cached_analyze(no) if no else None
        if bundle:
            _render_score_card(bundle)
        else:
            st.error("종목을 찾지 못했거나 분석 실패. (청약일정 외 종목은 고유번호로 검색하세요)")
