import streamlit as st

from database import (
    add_watchlist_item,
    delete_watchlist_item,
    get_watchlist,
    update_watchlist_status,
)
from utils.constants import BROKERS, WATCHLIST_STATUS_INTERESTED, WATCHLIST_STATUS_SUBSCRIBED, WATCHLIST_STATUS_MISSED
from utils.ipo_scraper import search_ipo_on_ipostock
from utils.timeutil import today_kst


def _dday(item: dict) -> str:
    if not item.get("sub_end"):
        return "-"
    delta = (item["sub_end"] - today_kst()).days
    if delta > 0:
        return f"D-{delta}"
    if delta == 0:
        return "D-Day 🔔"
    return "종료"


def _fmt_date(d) -> str:
    return d.strftime("%m/%d") if d else "-"


def _render_auto_search():
    col_input, col_btn = st.columns([4, 1])
    with col_input:
        name = st.text_input(
            "종목명 입력",
            key="wl_auto_name",
            placeholder="예) 마키나락스",
            label_visibility="collapsed",
        )
    with col_btn:
        search_clicked = st.button("🔍 조회", use_container_width=True, key="wl_auto_btn")

    if search_clicked:
        if not name.strip():
            st.warning("종목명을 입력하세요.")
        else:
            with st.spinner("ipostock.co.kr 조회 중..."):
                result = search_ipo_on_ipostock(name.strip())
            if result:
                st.session_state["wl_auto_result"] = result
            else:
                st.session_state["wl_auto_result"] = "failed"
            st.rerun()

    auto_result = st.session_state.get("wl_auto_result")
    if isinstance(auto_result, dict):
        st.success("✅ 조회 성공 — 내용을 확인하고 저장하세요.")
        _render_fields(
            key_prefix="auto",
            name_default=st.session_state.get("wl_auto_name", ""),
            sub_start_default=auto_result.get("sub_start"),
            sub_end_default=auto_result.get("sub_end"),
            listing_default=auto_result.get("listing_date"),
            price_default=auto_result.get("ipo_price") or 0,
            broker_default=auto_result.get("broker"),
        )
    elif auto_result == "failed":
        st.warning("❌ 조회 결과 없음 — 직접 입력하거나 종목명을 다시 확인하세요.")
        _render_fields(key_prefix="auto_fallback")


def _render_add_form():
    with st.expander("➕ 관심 종목 추가", expanded=False):
        mode = st.radio(
            "입력 방식",
            ["🔍 자동 조회", "✏️ 수동 입력"],
            horizontal=True,
            key="wl_mode",
        )
        st.divider()
        if mode == "🔍 자동 조회":
            _render_auto_search()
        else:
            _render_fields(key_prefix="manual")


def _render_fields(
    name_default="",
    sub_start_default=None,
    sub_end_default=None,
    listing_default=None,
    price_default=0,
    broker_default=None,
    key_prefix="",
):
    stock_name = st.text_input(
        "📌 종목명",
        value=name_default,
        key=f"{key_prefix}_wl_name",
        placeholder="종목명을 입력하세요",
    )

    broker_idx = BROKERS.index(broker_default) if broker_default and broker_default in BROKERS else 0
    broker = st.selectbox("🏦 증권사", BROKERS, index=broker_idx, key=f"{key_prefix}_wl_broker")

    col1, col2 = st.columns(2)
    with col1:
        sub_start = st.date_input(
            "📅 청약 시작일",
            value=sub_start_default,
            key=f"{key_prefix}_wl_sub_start",
        )
        listing_date = st.date_input(
            "🏛️ 상장일",
            value=listing_default,
            key=f"{key_prefix}_wl_listing",
        )
    with col2:
        sub_end = st.date_input(
            "📅 청약 종료일",
            value=sub_end_default,
            key=f"{key_prefix}_wl_sub_end",
        )
        ipo_price = st.number_input(
            "💰 공모가 (원)",
            min_value=0,
            value=int(price_default) if price_default else 0,
            step=100,
            key=f"{key_prefix}_wl_price",
        )

    memo = st.text_area("📝 메모", value="", height=68, placeholder="선택 입력", key=f"{key_prefix}_wl_memo")

    if st.button("💾 저장", type="primary", key=f"{key_prefix}_wl_save"):
        if not stock_name.strip():
            st.error("종목명을 입력하세요.")
            return
        data = {
            "stock_name":   stock_name.strip(),
            "broker":       broker if broker != "미정" else None,
            "sub_start":    sub_start if sub_start else None,
            "sub_end":      sub_end if sub_end else None,
            "listing_date": listing_date if listing_date else None,
            "ipo_price":    int(ipo_price) if ipo_price else None,
            "memo":         memo.strip(),
            "status":       WATCHLIST_STATUS_INTERESTED,
        }
        add_watchlist_item(data)
        st.session_state["wl_save_ok"] = stock_name.strip()
        st.session_state.pop("wl_auto_result", None)
        st.rerun()


# ── 메인 페이지 ────────────────────────────────────────────────────────────────

st.title("⭐ 관심 목록")

if msg := st.session_state.pop("wl_save_ok", None):
    st.success(f"'{msg}' 종목이 관심 목록에 추가되었습니다.")

_render_add_form()

st.divider()

# 목록 표시 옵션
show_all = st.toggle("완료 / 미신청 항목도 보기", value=False)
items = get_watchlist(status=None if show_all else WATCHLIST_STATUS_INTERESTED)

if not items:
    st.info("📭 관심 목록이 비어 있습니다. 위에서 종목을 추가하세요.")
    st.stop()

# 삭제 확인 상태
confirm_del_id = st.session_state.get("wl_confirm_del_id")

for item in items:
    dday = _dday(item)
    status = item["status"]

    # 상태 아이콘
    if status == WATCHLIST_STATUS_SUBSCRIBED:
        badge = "🟢 청약완료"
    elif status == WATCHLIST_STATUS_MISSED:
        badge = "🔴 미신청"
    else:
        badge = ""

    broker_str = item["broker"] or "미정"
    title_parts = [f"**{item['stock_name']}**", f"({broker_str})"]
    if badge:
        title_parts.append(badge)
    if dday != "-":
        title_parts.append(f"　`{dday}`")

    with st.container(border=True):
        col_title, col_actions = st.columns([4, 2])

        with col_title:
            st.markdown(" ".join(title_parts))
            date_parts = []
            if item.get("sub_start") or item.get("sub_end"):
                start_str = _fmt_date(item.get("sub_start"))
                end_str   = _fmt_date(item.get("sub_end"))
                date_parts.append(f"청약: {start_str} ~ {end_str}")
            if item.get("listing_date"):
                date_parts.append(f"상장: {_fmt_date(item['listing_date'])}")
            if item.get("ipo_price"):
                date_parts.append(f"공모가: ₩{item['ipo_price']:,}")
            if date_parts:
                st.caption("　".join(date_parts))
            if item.get("memo"):
                st.caption(f"📝 {item['memo']}")

        with col_actions:
            # 관심 상태일 때만 청약 신청 버튼 표시
            if status == WATCHLIST_STATUS_INTERESTED:
                if st.button("✅ 청약 신청", key=f"sub_{item['id']}", use_container_width=True):
                    st.session_state["prefill_from_watchlist"] = {
                        "stock_name":   item["stock_name"],
                        "sub_start":    item.get("sub_start"),
                        "date":         item["sub_end"] or today_kst(),
                        "ipo_price":    item["ipo_price"] or 0,
                        "broker":       item["broker"],
                        "listing_date": item.get("listing_date"),
                        "watchlist_id": item["id"],
                    }
                    st.switch_page("pages/input.py")

            if st.button("🗑️ 삭제", key=f"del_{item['id']}", use_container_width=True):
                st.session_state["wl_confirm_del_id"] = item["id"]
                st.rerun()

    # 삭제 확인 UI
    if confirm_del_id == item["id"]:
        st.warning(f"**'{item['stock_name']}'** 을(를) 관심 목록에서 삭제하시겠습니까?")
        c1, c2, _ = st.columns([1, 1, 5])
        with c1:
            if st.button("삭제 확인", type="primary", key=f"del_ok_{item['id']}"):
                delete_watchlist_item(item["id"])
                st.session_state.pop("wl_confirm_del_id", None)
                st.rerun()
        with c2:
            if st.button("취소", key=f"del_cancel_{item['id']}"):
                st.session_state.pop("wl_confirm_del_id", None)
                st.rerun()
