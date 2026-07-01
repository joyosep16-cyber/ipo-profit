"""공모주 분석 페이지 — 수요예측 점수 분석 (analyzer 엔진).

청약일정 목록에서 종목을 고르거나 직접 검색하여,
기관 경쟁률·의무보유확약·유통가능규모·장외 괴리율·증거금을 분석하고
가이드 스코어링(총점/추천 등급)을 카드로 표시한다.
스팩/리츠는 점수 산정에서 제외하고 안내만 표시한다.
"""
from datetime import datetime

import streamlit as st

from database import add_watchlist_item, get_setting
from utils.constants import WATCHLIST_STATUS_INTERESTED
from utils import discord_notifier
from utils.timeutil import now_kst_naive
from analyzer import evaluator, scraper, service

st.title("🔍 공모주 분석")
st.caption("38커뮤니케이션 수요예측 결과 + DART 교차검증 기반 점수 분석")


# DART 키를 DB 설정에서 환경변수로 주입 (analyzer.config.get_dart_api_key 가 읽음)
import os
_dart_key = get_setting("DART_API_KEY", "")
if _dart_key:
    os.environ["DART_API_KEY"] = _dart_key


@st.cache_data(ttl=1800, show_spinner=False)
def _cached_schedule() -> list[dict]:
    # 스팩은 전용 분석을 위해 목록에 노출(리츠만 제외) + 이미 상장한 종목 제거
    return scraper.fetch_schedule(exclude_spac=False, drop_listed=True)


def _fmt_candidate(c: dict) -> str:
    """드롭다운 표시: '종목명 · 청약 YYYY-MM-DD~YYYY-MM-DD (no=XXXX)'."""
    ss, se = c.get("sub_start"), c.get("sub_end")
    if ss and se:
        sched = f"청약 {ss:%Y-%m-%d}~{se:%Y-%m-%d}"
    elif ss:
        sched = f"청약 {ss:%Y-%m-%d}~"
    else:
        sched = "청약일 미정"
    return f"{c['name']}  ·  {sched}  (no={c['no']})"


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


def _render_spac_card(bundle: dict) -> None:
    """스팩(SPAC) 전용 분석 카드 — 기관경쟁률·의무보유확약만으로 판정."""
    merged = bundle["merged"]
    metrics = bundle["metrics"]
    name = bundle["name"]
    spac = bundle["spac_result"]
    raw_warn = "" if metrics.get("raw_verified") else " ⚠️추정"

    st.subheader(f"🟦 {name} · 스팩(SPAC) 분석")
    price = merged.get("confirmed_price")
    c1, c2, c3 = st.columns(3)
    c1.metric("확정 공모가", f"{int(price):,}원" if price else "-")
    c2.metric("상장 예정일", str(merged.get("listing_date") or "-"))
    c3.metric("데이터 신뢰도", merged.get("data_quality") or ("추정" if raw_warn else "-"))

    st.divider()
    m1, m2 = st.columns(2)
    m1.metric("기관 경쟁률", f"{metrics['inst_competition']:,.2f} : 1{raw_warn}")
    m2.metric("의무보유확약", f"{metrics['lockup_ratio']:.2f}%{raw_warn}")
    st.caption(f"경쟁률 판정: {spac['comp_grade']}　·　확약: "
               + ("➕ 확보(>0%)" if spac["has_lockup"] else "⚪ 0% (스팩 전형)"))

    st.divider()
    verdict_line = f"{spac['emoji']} **{spac['verdict']}**\n\n💡 {spac['action']}"
    if spac["verdict"] == "적극 관심":
        st.success(verdict_line)
    elif spac["verdict"] == "신중":
        st.error(verdict_line)
    else:
        st.warning(verdict_line)
    st.caption("스팩은 경쟁률·의무보유확약만으로 판정합니다(유통규모·장외 제외, 공모가 보통 2,000원). "
               "상장 당일 확약 물량만큼 유통이 줄어 2,000원 상회 가능성이 높아집니다.")

    if st.button("💬 Discord 발송", key=f"disc_spac_{bundle['no']}", use_container_width=True):
        if not (os.getenv("DISCORD_WEBHOOK_URL") or get_setting("DISCORD_WEBHOOK_URL")):
            st.error("Discord 웹훅이 설정되지 않았습니다. 설정 페이지에서 등록하세요.")
        else:
            discord_notifier.send_spac_analysis(merged, spac, metrics)
            st.success("Discord로 발송했습니다.")


def _render_score_card(bundle: dict) -> None:
    merged = bundle["merged"]
    metrics = bundle["metrics"]
    is_spac = bundle["is_spac"]
    name = bundle["name"]
    result = bundle["result"]   # 기본 결과(동시상장 미적용). 아래에서 토글로 재계산.

    # 리츠: 분석 제외 안내만 / 스팩: 경쟁률·확약 전용 분석 카드
    if bundle.get("is_reit"):
        st.info(f"ℹ️ **{name}** 은(는) 리츠(REIT) 종목으로 공모주 점수 분석 대상에서 제외됩니다.")
        return
    if is_spac:
        _render_spac_card(bundle)
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
        if metrics.get("circulating_missing") and not metrics.get("circulating_eok"):
            m3.metric("유통가능규모", "N/A", help="38에 유통가능물량 표가 없는 종목. 아래에서 수동 입력하세요.")
        else:
            m3.metric("유통가능규모", f"{metrics['circulating_eok']:,.1f}억원")
        prem = metrics["otc_premium"]
        prem_min = metrics.get("otc_min_premium")
        if metrics.get("otc_missing"):
            m4.metric("장외 괴리율", "없음", help="매도호가·매수호가가 모두 있어야 시세로 인정 (없으면 -2점)")
        else:
            m4.metric("장외 괴리율(평균)", f"{prem:+.2f}%" if prem is not None else "N/A")

    # 장외 괴리율 — 평균/최소 함께 표기 (분석가는 최소호가 기준을 보기도 함)
    if not is_spac and not metrics.get("otc_missing") and prem is not None:
        ap, mp = metrics.get("otc_avg_price"), metrics.get("otc_min_price")
        min_str = f"최소 **{prem_min:+.2f}%**" + (f" ({mp:,.0f}원)" if mp else "") if prem_min is not None else "최소 N/A"
        avg_extra = f" ({ap:,.0f}원)" if ap else ""
        st.caption(f"장외 괴리율 — 평균 **{prem:+.2f}%**{avg_extra}　·　{min_str}")

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

    # 동시상장 토글 — 같은 상장일에 동시상장 종목이 있으면 장외 칸 -2 (무조건).
    # 38에 종목별 상장일 목록이 없어 자동 판정이 어려우므로 수동 지정한다.
    # (무거운 크롤링은 캐시하고 점수만 재계산 → 체크 즉시 반영)
    if not is_spac:
        is_simul = st.checkbox(
            "📅 동시상장 (같은 날 상장하는 다른 종목 있음) → 장외 -2점",
            key=f"simul_{bundle['no']}",
            help="상장 예정일이 같은 종목이 있으면 체크하세요. 장외가격 점수가 -2로 대체됩니다.")

        # 유통가능물량 데이터가 38에 없는 종목은 수동 입력으로 보정 (분석가/DART 값)
        score_metrics = metrics
        if metrics.get("circulating_missing") and not metrics.get("circulating_eok"):
            cprice = merged.get("confirmed_price") or 0
            st.warning("⚠️ 38에 유통가능물량 표가 없어 자동 산출이 안 됩니다. "
                       "아래에 값을 입력하면 점수에 반영됩니다. (미입력 시 유통 0점)")
            if cprice > 0:
                # 주식수 입력 → 확정공모가를 곱해 금액(억원) 자동 산출
                manual_shares = st.number_input(
                    "유통가능 주식수 입력 (주)", min_value=0, value=0, step=1000,
                    key=f"circ_sh_{bundle['no']}",
                    help="DART 증권신고서/분석가 자료의 '공모 후 유통가능물량' 주식수를 입력하면 "
                         "확정공모가를 곱해 금액(억원)을 계산합니다.")
                if manual_shares > 0:
                    manual_eok = evaluator.circulating_eok_from_shares(manual_shares, cprice)
                    st.caption(f"{manual_shares:,}주 × {int(cprice):,}원 = 약 **{manual_eok:,.1f}억원**")
                    score_metrics = {**metrics, "circulating_eok": manual_eok,
                                     "circulating_missing": False}
            else:
                # 확정공모가가 없어 곱셈 불가 → 억원 직접 입력 폴백
                manual_eok = st.number_input(
                    "유통가능규모 직접 입력 (억원)", min_value=0.0, value=0.0, step=10.0,
                    key=f"circ_{bundle['no']}",
                    help="확정공모가가 없어 자동 계산이 불가합니다. 금액(억원)을 직접 입력하세요.")
                if manual_eok > 0:
                    score_metrics = {**metrics, "circulating_eok": manual_eok,
                                     "circulating_missing": False}

        # 캐시된 bundle 을 변형하지 않도록 지역 변수에만 재계산 결과 보관
        result = evaluator.evaluate_ipo_score(
            score_metrics, is_simultaneous=is_simul, is_spac_reit=is_spac)
        # 장외 최소호가 기준 총점(분석가 방식) — 장외 칸만 최소 괴리율로 교체
        score_metrics_min = {**score_metrics, "otc_premium": metrics.get("otc_min_premium")}
        result_min = evaluator.evaluate_ipo_score(
            score_metrics_min, is_simultaneous=is_simul, is_spac_reit=is_spac)

    # 점수 / 추천
    if is_spac:
        st.info(f"ℹ️ {result['notice']}")
    else:
        total = result["total"]
        grade = result["grade"]
        verdict = result["verdict"]
        if total >= 16:
            st.success(f"🎯 총점 **{total}점**(장외 평균) · {grade} · **{verdict}**\n\n💡 {result['action']}")
        elif total >= 10:
            st.warning(f"🎯 총점 **{total}점**(장외 평균) · {grade} · {verdict}\n\n💡 {result['action']}")
        else:
            st.error(f"🎯 총점 **{total}점**(장외 평균) · {grade} · {verdict}\n\n💡 {result['action']}")
        # 장외 최소호가 기준 총점도 함께 표시
        total_min = result_min["total"]
        st.caption(f"📉 장외 **최소호가** 기준 총점: **{total_min}점** · {result_min['grade']} "
                   f"({result_min['verdict']})" + ("　— 자동알림 기준" if total_min >= 16 else ""))

    # 액션 버튼
    b1, b2 = st.columns(2)
    with b1:
        if st.button("💬 Discord 발송", key=f"disc_{bundle['no']}", use_container_width=True):
            if not (os.getenv("DISCORD_WEBHOOK_URL") or get_setting("DISCORD_WEBHOOK_URL")):
                st.error("Discord 웹훅이 설정되지 않았습니다. 설정 페이지에서 등록하세요.")
            else:
                # score_metrics: 수동 보정(유통가능규모)이 반영된 지표 — 화면 점수와 일치시킴
                discord_notifier.send_analysis_score(merged, result, score_metrics, result_min)
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
                "analyzed_at": now_kst_naive(),
            })
            st.success(f"'{name}' 을(를) 관심목록에 추가했습니다. (점수 {result.get('total')})")


# ============================================================================
# 탭 구성
# ============================================================================
tab_list, tab_search = st.tabs(["📅 청약일정 목록", "🔎 직접 검색"])

with tab_list:
    cols = st.columns([2, 1, 1])
    with cols[1]:
        if st.button("🔄 목록 새로고침", use_container_width=True):
            _cached_schedule.clear()
    with cols[2]:
        # 분석 결과는 30분 캐시된다. 코드/사이트 데이터가 바뀌었는데 옛 결과가
        # 남아있을 때 이 버튼으로 분석 캐시와 표시 중인 카드를 모두 비운다.
        if st.button("🧹 분석 캐시 비우기", use_container_width=True):
            _cached_analyze.clear()
            st.session_state.pop("analysis_bundle", None)
            st.success("분석 캐시를 비웠습니다. 다시 분석을 실행하세요.")
    candidates = _cached_schedule()
    if not candidates:
        st.warning("청약일정을 불러오지 못했습니다. (네트워크 또는 사이트 상태 확인)")
    else:
        # 청약 시작일 빠른 순 정렬(미상은 뒤로) + 드롭다운에 청약일정 함께 표시
        candidates = sorted(
            candidates,
            key=lambda c: (c.get("sub_start") is None, str(c.get("sub_start") or "")))
        names = [_fmt_candidate(c) for c in candidates]
        idx = st.selectbox("분석할 종목 선택", range(len(candidates)),
                           format_func=lambda i: names[i])
        if st.button("📊 분석 실행", type="primary"):
            with st.spinner("분석 중... (크롤링·DART 조회로 수 초 소요)"):
                bundle = _cached_analyze(candidates[idx]["no"])
            if bundle:
                st.session_state["analysis_bundle"] = bundle
            else:
                st.session_state.pop("analysis_bundle", None)
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
            st.session_state["analysis_bundle"] = bundle
        else:
            st.session_state.pop("analysis_bundle", None)
            st.error("종목을 찾지 못했거나 분석 실패. (청약일정 외 종목은 고유번호로 검색하세요)")

# 분석 결과 카드 — 탭 밖에서 렌더해야 동시상장 체크박스 상호작용에도 카드가 유지된다.
_bundle = st.session_state.get("analysis_bundle")
if _bundle:
    st.divider()
    _render_score_card(_bundle)
