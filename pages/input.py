import os
from datetime import date

import streamlit as st

from database import add_record, get_record_by_id, update_record, update_watchlist_status
from utils.calculator import calc_return_rate, get_return_label
from utils.config import get_env_float
from utils.constants import BROKERS, SUB_TYPES, ENV_HIGH_RETURN_THRESHOLD, WATCHLIST_STATUS_SUBSCRIBED
from utils.discord_notifier import (
    send_high_return_alert,
    send_record_added,
    send_record_updated,
)

edit_id = st.session_state.get("edit_record_id")
is_edit = edit_id is not None

existing = None
if is_edit:
    existing = get_record_by_id(edit_id)
    if not existing:
        st.error("수정할 기록을 찾을 수 없습니다.")
        st.session_state.pop("edit_record_id", None)
        st.switch_page("pages/home.py")
        st.stop()

st.title("✏️ 공모주 수정" if is_edit else "✏️ 공모주 추가")


_MI_KEYS = [
    "mi_sub_start", "mi_date", "mi_stock_name", "mi_broker", "mi_ipo_price",
    "mi_sub_type", "mi_sub_result", "mi_quantity", "mi_sell_date",
    "mi_sell_price", "mi_memo", "_mi_edit_id", "_mi_watchlist_id",
]


def _clear_input_state():
    for k in _MI_KEYS:
        st.session_state.pop(k, None)


def _manual_input(existing=None, is_edit=False, edit_id=None):
    # prefill은 관심 목록 → 이 페이지로 최초 진입 시에만 존재
    prefill = st.session_state.pop("prefill_from_watchlist", None)

    # watchlist_id 재실행 간 보존 (저장 시 상태 변경에 사용)
    if prefill and prefill.get("watchlist_id"):
        st.session_state.setdefault("_mi_watchlist_id", prefill["watchlist_id"])

    # 수정 대상 레코드가 바뀌면 이전 상태 초기화
    if is_edit and st.session_state.get("_mi_edit_id") != edit_id:
        _clear_input_state()
        st.session_state["_mi_edit_id"] = edit_id

    # 위젯 초기값을 session_state에 1회만 설정 (setdefault: 이미 있으면 유지)
    if existing:
        st.session_state.setdefault("mi_sub_start",  existing.get("sub_start"))
        st.session_state.setdefault("mi_date",       existing["date"])
        st.session_state.setdefault("mi_stock_name", existing["stock_name"])
        st.session_state.setdefault("mi_broker",     existing["broker"] if existing["broker"] in BROKERS else "기타")
        st.session_state.setdefault("mi_ipo_price",  int(existing["ipo_price"]))
        st.session_state.setdefault("mi_sub_type",   existing["sub_type"] if existing["sub_type"] in SUB_TYPES else SUB_TYPES[0])
        st.session_state.setdefault("mi_sub_result", existing.get("sub_result", "당첨"))
        st.session_state.setdefault("mi_quantity",   int(existing["quantity"]))
        st.session_state.setdefault("mi_sell_date",  existing.get("sell_date"))
        st.session_state.setdefault("mi_sell_price", int(existing.get("sell_price") or 0))
        st.session_state.setdefault("mi_memo",       existing["memo"] or "")
    elif prefill:
        st.session_state.setdefault("mi_sub_start",  prefill.get("sub_start"))
        st.session_state.setdefault("mi_date",       prefill.get("date") or date.today())
        st.session_state.setdefault("mi_stock_name", prefill.get("stock_name", ""))
        _b = prefill.get("broker")
        st.session_state.setdefault("mi_broker",     _b if _b and _b in BROKERS else "기타")
        st.session_state.setdefault("mi_ipo_price",  int(prefill.get("ipo_price") or 0))
        st.session_state.setdefault("mi_sell_date",  prefill.get("listing_date"))

    # 신규 입력 모드 기본값 (위 두 블록에서 미처리된 키에만 적용)
    st.session_state.setdefault("mi_sub_start",  None)
    st.session_state.setdefault("mi_date",       date.today())
    st.session_state.setdefault("mi_stock_name", "")
    st.session_state.setdefault("mi_broker",     "기타")
    st.session_state.setdefault("mi_ipo_price",  0)
    st.session_state.setdefault("mi_sub_type",   SUB_TYPES[0])
    st.session_state.setdefault("mi_sub_result", "당첨")
    st.session_state.setdefault("mi_quantity",   0)
    st.session_state.setdefault("mi_sell_date",  None)
    st.session_state.setdefault("mi_sell_price", 0)
    st.session_state.setdefault("mi_memo",       "")

    col1, col2 = st.columns(2)

    with col1:
        sub_start  = st.date_input("📅 청약 시작일",    key="mi_sub_start",
                                   help="청약 기간 첫째 날 (선택 입력)")
        input_date = st.date_input("📅 청약 종료일",    key="mi_date",
                                   help="청약 기간 마지막 날")
        stock_name = st.text_input("📌 종목명",         key="mi_stock_name", placeholder="예) 삼성스팩")
        broker     = st.selectbox("🏦 증권사",          BROKERS, key="mi_broker")
        ipo_price  = st.number_input("💰 공모가 (원)",  min_value=0, step=100, key="mi_ipo_price")

    with col2:
        sub_type   = st.radio("📋 청약방식",  SUB_TYPES,          key="mi_sub_type",   horizontal=True)
        sub_result = st.radio("🎯 당첨 여부", ["당첨", "미당첨"], key="mi_sub_result", horizontal=True)
        is_miss    = sub_result == "미당첨"
        quantity   = st.number_input("📦 수량 (주)",    min_value=0, step=1,   key="mi_quantity",   disabled=is_miss)
        sell_date  = st.date_input(
            "🏛️ 상장일", key="mi_sell_date",
            help="상장일을 입력하세요. 보통 매도일과 동일합니다.",
            disabled=is_miss,
        )
        sell_price = st.number_input(
            "💲 매도가 (원)", min_value=0, step=100, key="mi_sell_price",
            help="매도한 가격을 입력하면 총수익과 수익률이 자동 계산됩니다.",
            disabled=is_miss,
        )
        memo = st.text_area("📝 메모", key="mi_memo", height=68, placeholder="선택 입력")

    st.divider()
    if is_miss:
        profit      = 0
        return_rate = None
        st.caption("미당첨 종목은 수익이 0으로 기록됩니다.")
    else:
        if int(sell_price) > 0:
            profit      = (int(sell_price) - int(ipo_price)) * int(quantity)
            return_rate = calc_return_rate(profit, int(ipo_price), int(quantity))
        else:
            profit      = 0
            return_rate = None
        if ipo_price > 0 and quantity > 0 and sell_price > 0:
            c1, c2, c3 = st.columns(3)
            profit_str  = f"+₩{profit:,}" if profit >= 0 else f"-₩{abs(profit):,}"
            c1.metric("💵 총수익 (자동계산)", profit_str)
            c2.metric("📈 수익률 (자동계산)", f"{return_rate:.2f}%" if return_rate is not None else "-")
            c3.metric("💰 투자원금", f"₩{int(ipo_price) * int(quantity):,}")
        else:
            st.caption("공모가, 수량, 매도가를 모두 입력하면 총수익과 수익률이 자동 계산됩니다.")

    st.divider()

    col_save, col_cancel, _ = st.columns([1, 1, 4])
    with col_save:
        save_clicked   = st.button("💾 저장", type="primary", use_container_width=True)
    with col_cancel:
        cancel_clicked = st.button("취소",                    use_container_width=True)

    if cancel_clicked:
        _clear_input_state()
        st.session_state.pop("edit_record_id", None)
        st.switch_page("pages/home.py")

    if save_clicked:
        if not stock_name.strip():
            st.error("종목명을 입력하세요.")
            st.stop()
        if ipo_price <= 0:
            st.error("공모가를 입력하세요.")
            st.stop()

        data = {
            "date":        input_date,
            "sub_start":   sub_start if sub_start else None,
            "stock_name":  stock_name.strip(),
            "broker":      broker,
            "ipo_price":   int(ipo_price),
            "sub_type":    sub_type,
            "sub_result":  sub_result,
            "sell_date":   None if is_miss else (sell_date if sell_date else None),
            "sell_price":  0 if is_miss else int(sell_price),
            "profit":      profit,
            "quantity":    0 if is_miss else int(quantity),
            "return_rate": return_rate,
            "memo":        memo.strip() or get_return_label(return_rate, sub_result),
        }

        threshold = get_env_float(ENV_HIGH_RETURN_THRESHOLD, 200.0)

        if is_edit:
            updated = update_record(edit_id, data)
            if updated:
                send_record_updated(existing, updated)
                if return_rate is not None and return_rate >= threshold:
                    send_high_return_alert(updated)
            st.session_state.pop("edit_record_id", None)
            st.session_state["success_message"] = f"'{stock_name}' 종목이 수정되었습니다."
        else:
            added = add_record(data)
            if added:
                send_record_added(added)
                if return_rate is not None and return_rate >= threshold:
                    send_high_return_alert(added)
            watchlist_id = st.session_state.pop("_mi_watchlist_id", None)
            if watchlist_id:
                update_watchlist_status(watchlist_id, WATCHLIST_STATUS_SUBSCRIBED)
            st.session_state["success_message"] = f"'{stock_name}' 종목이 추가되었습니다."

        _clear_input_state()
        st.switch_page("pages/home.py")


def _excel_upload():
    st.markdown("**엑셀 파일로 여러 종목을 한 번에 입력합니다.**")
    st.caption("💡 '수익 현황' 화면의 '엑셀 다운로드'로 받은 파일을 양식으로 활용하세요.")

    file = st.file_uploader("엑셀 파일 선택 (.xlsx)", type=["xlsx"])
    if file is None:
        return

    try:
        from utils.excel_handler import import_from_excel
        records = import_from_excel(file)
    except ValueError as e:
        st.error(str(e))
        return

    if not records:
        st.warning("파일에 데이터가 없습니다.")
        return

    required_cols = {"date", "stock_name", "ipo_price"}
    if not required_cols.issubset(records[0].keys()):
        missing = required_cols - records[0].keys()
        st.error(f"필수 컬럼이 누락되었습니다: {', '.join(missing)}")
        return

    import pandas as pd
    st.success(f"✅ {len(records)}개 종목을 읽었습니다. 아래 내용을 확인 후 저장하세요.")
    st.dataframe(pd.DataFrame(records), use_container_width=True, hide_index=True)

    if st.button("💾 일괄 저장", type="primary"):
        success_count = 0
        fail_messages = []
        for i, r in enumerate(records):
            try:
                sell_price = int(r.get("sell_price") or 0)
                ipo_price = int(r.get("ipo_price", 0))
                quantity = int(r.get("quantity") or 0)
                if sell_price > 0:
                    profit = (sell_price - ipo_price) * quantity
                else:
                    profit = int(r.get("profit") or 0)
                _rr = r.get("return_rate")
                return_rate = float(_rr) if _rr is not None else calc_return_rate(profit, ipo_price, quantity)

                data = {
                    "date": r["date"],
                    "sub_start": r.get("sub_start"),
                    "stock_name": str(r["stock_name"]),
                    "broker": str(r.get("broker", "기타")),
                    "ipo_price": ipo_price,
                    "sub_type": str(r.get("sub_type", "균등")),
                    "sub_result": str(r.get("sub_result", "당첨")),
                    "sell_date": r.get("sell_date"),
                    "sell_price": sell_price,
                    "profit": profit,
                    "quantity": quantity,
                    "return_rate": return_rate,
                    "memo": str(r.get("memo", "")) or get_return_label(return_rate, str(r.get("sub_result", "당첨"))),
                }
                add_record(data)
                success_count += 1
            except Exception as e:
                name = str(r.get("stock_name", f"{i + 1}번째 행"))
                fail_messages.append(f"• {name}: {e}")

        fail_count = len(fail_messages)
        if fail_messages:
            st.error("저장 실패 항목:\n" + "\n".join(fail_messages))
        if success_count:
            suffix = f" / {fail_count}개 실패" if fail_count else ""
            st.success(f"✅ {success_count}개 저장 완료{suffix}")
            st.session_state["success_message"] = f"엑셀에서 {success_count}개 종목이 추가되었습니다."
            st.switch_page("pages/home.py")
        else:
            st.error("저장에 실패했습니다. 파일 내용을 확인해 주세요.")


if is_edit:
    _manual_input(existing=existing, is_edit=True, edit_id=edit_id)
else:
    tab1, tab2 = st.tabs(["✏️ 수동 입력", "📂 엑셀 업로드"])
    with tab1:
        _manual_input(existing=None, is_edit=False, edit_id=None)
    with tab2:
        _excel_upload()
