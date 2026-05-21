import pandas as pd
import streamlit as st

from database import get_yearly_summary, upsert_yearly_note
from utils.calculator import format_krw

st.title("📅 연도별 수익 요약")

summaries = get_yearly_summary()

if not summaries:
    st.info("📭 데이터가 없습니다. 먼저 공모주 기록을 추가해 주세요.")
    st.stop()

# 연도별 요약 테이블
rows = []
prev_profit = None
for s in summaries:
    avg_str = f"{s['avg_return_rate']:.1f}%" if s["avg_return_rate"] is not None else "-"
    delta = ""
    if prev_profit is not None:
        diff = s["total_profit"] - prev_profit
        delta = f"+₩{diff:,}" if diff >= 0 else f"-₩{abs(diff):,}"
    rows.append({
        "연도": f"{s['year']}년",
        "총수익": format_krw(s["total_profit"]),
        "종목 수": f"{s['count']}개",
        "평균 수익률": avg_str,
        "전년 대비": delta,
        "메모": s["note"] or "",
    })
    prev_profit = s["total_profit"]

df = pd.DataFrame(rows)
st.dataframe(df, use_container_width=True, hide_index=True)

# 전체 누적 합계
st.divider()
total = sum(s["total_profit"] for s in summaries)
st.metric("📦 전체 누적 수익", format_krw(total))

st.divider()

# 메모 수정
st.subheader("📝 메모 수정")
year_map = {f"{s['year']}년": s for s in summaries}
selected_str = st.selectbox("연도 선택", list(year_map.keys()))
selected = year_map[selected_str]

new_note = st.text_input("메모", value=selected["note"] or "", placeholder="예) 역대급 수익 달성!")

if st.button("저장", type="primary"):
    upsert_yearly_note(selected["year"], new_note)
    st.success("메모가 저장되었습니다.")
    st.rerun()
