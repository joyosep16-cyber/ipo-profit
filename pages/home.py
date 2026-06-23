import pandas as pd
import streamlit as st

from database import delete_record, get_available_years, get_records, get_setting
from utils.calculator import format_krw, get_return_label, get_win_rate
from utils.timeutil import now_kst, today_kst
from utils.discord_notifier import send_record_deleted
from utils.excel_handler import export_to_excel

st.title("📊 공모주 수익 현황")

if msg := st.session_state.pop("success_message", None):
    st.success(msg)

# 연도 필터
years = get_available_years()
current_year = today_kst().year
all_years = sorted(set([current_year] + years), reverse=True)
year_options = ["전체"] + [f"{y}년" for y in all_years]

selected_year_str = st.radio(
    "연도",
    year_options,
    index=1 if f"{current_year}년" in year_options else 0,
    horizontal=True,
    label_visibility="collapsed",
)
filter_year = None if selected_year_str == "전체" else int(selected_year_str.replace("년", ""))

records = get_records(year=filter_year)

# 목표 달성률 (데이터 있을 때만)
today = today_kst()
try:
    monthly_goal = int(get_setting("MONTHLY_GOAL") or "0")
except ValueError:
    monthly_goal = 0
try:
    yearly_goal = int(get_setting("YEARLY_GOAL") or "0")
except ValueError:
    yearly_goal = 0

if records and monthly_goal > 0:
    this_month_profit = sum(
        r["profit"] for r in records
        if r["date"] and r["date"].year == today.year and r["date"].month == today.month
    )
    pct = max(0.0, min(this_month_profit / monthly_goal, 1.0))
    st.progress(pct, text=f"이달 목표 {format_krw(monthly_goal)} 중 {format_krw(this_month_profit)} 달성 ({this_month_profit / monthly_goal * 100:.0f}%)")

if records and yearly_goal > 0:
    this_year_profit = sum(
        r["profit"] for r in records
        if r["date"] and r["date"].year == today.year
    )
    pct_y = max(0.0, min(this_year_profit / yearly_goal, 1.0))
    st.progress(pct_y, text=f"올해 목표 {format_krw(yearly_goal)} 중 {format_krw(this_year_profit)} 달성 ({this_year_profit / yearly_goal * 100:.0f}%)")

# 매도 미입력 경고 (7일 이상 경과한 종목)
if records:
    pending = [
        r for r in records
        if not r.get("sell_price") and r.get("sub_result", "당첨") == "당첨"
        and (today - r["date"]).days >= 7
    ]
    if pending:
        st.warning(f"⚠️ 매도가 미입력 종목 {len(pending)}개가 7일 이상 경과했습니다.")

if not records:
    st.info("📭 등록된 공모주 기록이 없습니다.")
    if st.button("+ 새 종목 추가", type="primary"):
        st.session_state.pop("edit_record_id", None)
        st.switch_page("pages/input.py")
    st.stop()

# 상세 필터
with st.expander("🔍 상세 필터", expanded=False):
    col_f1, col_f2 = st.columns(2)
    with col_f1:
        broker_filter = st.multiselect(
            "증권사",
            sorted(set(r["broker"] for r in records)),
            placeholder="전체 (미선택 시)",
        )
        search_name = st.text_input("🔍 종목명 검색", placeholder="종목명 입력...")
    with col_f2:
        sub_filter = st.multiselect(
            "청약방식",
            ["균등", "비례"],
            placeholder="전체 (미선택 시)",
        )
        result_filter = st.multiselect(
            "당첨 여부",
            ["당첨", "미당첨"],
            placeholder="전체 (미선택 시)",
        )

    col_r1, col_r2 = st.columns(2)
    with col_r1:
        min_rate = st.number_input("수익률 최소 (%)", value=None, placeholder="제한 없음", step=1.0)
    with col_r2:
        max_rate = st.number_input("수익률 최대 (%)", value=None, placeholder="제한 없음", step=1.0)

if broker_filter:
    records = [r for r in records if r["broker"] in broker_filter]
if sub_filter:
    records = [r for r in records if r["sub_type"] in sub_filter]
if result_filter:
    records = [r for r in records if r.get("sub_result", "당첨") in result_filter]
if search_name:
    records = [r for r in records if search_name.lower() in r["stock_name"].lower()]
if min_rate is not None:
    records = [r for r in records if r.get("return_rate") is not None and r["return_rate"] >= min_rate]
if max_rate is not None:
    records = [r for r in records if r.get("return_rate") is not None and r["return_rate"] <= max_rate]

if not records:
    st.info("📭 선택한 필터에 해당하는 기록이 없습니다.")
    st.stop()

# 테이블 구성
def _fmt_date(d) -> str:
    return f"{d.year}년 {d.month}월 {d.day}일" if d else "-"

def _fmt_sub_period(start, end) -> str:
    if start and end:
        return f"{_fmt_date(start)}~{_fmt_date(end)}"
    return _fmt_date(end)

rows = []
for r in records:
    rr = r.get("return_rate")
    sp = r.get("sell_price")
    memo_text = r.get("memo", "") or get_return_label(r.get("return_rate"), r.get("sub_result", "당첨"))
    memo_display = (memo_text[:15] + "...") if len(memo_text) > 15 else memo_text
    rows.append({
        "청약일": _fmt_sub_period(r.get("sub_start"), r.get("date")),
        "상장일": _fmt_date(r.get("sell_date")),
        "종목": r["stock_name"],
        "증권사": r["broker"],
        "공모가": f"₩{r['ipo_price']:,}",
        "매도가": f"₩{sp:,}" if sp else "-",
        "청약": r["sub_type"],
        "당첨": r.get("sub_result", "당첨"),
        "총수익": f"+₩{r['profit']:,}" if r["profit"] >= 0 else f"-₩{abs(r['profit']):,}",
        "수량": f"{r['quantity']}주" if r["quantity"] else "-",
        "수익률": f"{rr:.2f}%" if rr is not None else "-",
        "메모": memo_display,
    })

df = pd.DataFrame(rows)
st.dataframe(df, use_container_width=True, hide_index=True)

# 하단 요약 지표
st.divider()
total_profit = sum(r["profit"] for r in records)
valid_rates = [r["return_rate"] for r in records if r.get("return_rate") is not None]
avg_rate = sum(valid_rates) / len(valid_rates) if valid_rates else 0.0
win_rate = get_win_rate(records)

col1, col2, col3, col4 = st.columns(4)
col1.metric("합계", format_krw(total_profit, signed=True))
col2.metric("종목 수", f"{len(records)}개")
col3.metric("평균 수익률", f"{avg_rate:.1f}%")
col4.metric("승률", f"{win_rate:.1f}%")

# 엑셀 다운로드
excel_bytes = export_to_excel(records)
if excel_bytes:
    st.download_button(
        "📥 엑셀 다운로드",
        data=excel_bytes,
        file_name=f"공모주수익_{now_kst().strftime('%Y%m%d')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

st.divider()

# 종목 추가 / 수정 / 삭제
col_add, _ = st.columns([2, 8])
with col_add:
    if st.button("+ 새 종목 추가", type="primary"):
        st.session_state.pop("edit_record_id", None)
        st.switch_page("pages/input.py")

options = {
    f"{r['date']}  |  {r['stock_name']}  ({r['broker']})": r["id"]
    for r in records
}
selected_label = st.selectbox(
    "수정 / 삭제할 종목 선택",
    ["-- 선택하세요 --"] + list(options.keys()),
)

if selected_label != "-- 선택하세요 --":
    selected_id = options[selected_label]
    col_e, col_d, _ = st.columns([1, 1, 6])

    with col_e:
        if st.button("✏️ 수정", use_container_width=True):
            st.session_state["edit_record_id"] = selected_id
            st.switch_page("pages/input.py")

    with col_d:
        if st.button("🗑️ 삭제", use_container_width=True):
            st.session_state["confirm_delete_id"] = selected_id

    if st.session_state.get("confirm_delete_id") == selected_id:
        raw = selected_label.split("  |  ", 1)[-1]
        stock = raw.rsplit("  (", 1)[0].strip()
        st.warning(f"**'{stock}'** 종목을 삭제하시겠습니까? 이 작업은 되돌릴 수 없습니다.")
        c1, c2, _ = st.columns([1, 1, 6])
        with c1:
            if st.button("삭제 확인", type="primary"):
                deleted = delete_record(selected_id)
                if deleted:
                    send_record_deleted(deleted)
                st.session_state.pop("confirm_delete_id", None)
                st.session_state["success_message"] = f"'{stock}' 종목이 삭제되었습니다."
                st.rerun()
        with c2:
            if st.button("취소"):
                st.session_state.pop("confirm_delete_id", None)
                st.rerun()
