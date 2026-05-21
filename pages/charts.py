import pandas as pd
import plotly.express as px
import streamlit as st

from database import get_records
from utils.calculator import format_krw, get_win_rate
from utils.constants import SUB_TYPE_COLORS, PROFIT_COLORS

st.title("📉 통계 & 차트")

records = get_records()

if not records:
    st.info("📭 데이터가 없습니다. 먼저 공모주 기록을 추가해 주세요.")
    st.stop()

df = pd.DataFrame(records)
df["date"] = pd.to_datetime(df["date"])
df["year"] = df["date"].dt.year
df["month"] = df["date"].dt.month

# 미당첨 제외 토글
if "sub_result" in df.columns:
    exclude_miss = st.toggle("미당첨 제외하고 통계 보기", value=True)
    if exclude_miss:
        df = df[df["sub_result"] != "미당첨"].copy()
else:
    exclude_miss = False

# 핵심 지표 카드
if df.empty:
    st.info("선택한 조건에 해당하는 데이터가 없습니다.")
    st.stop()

total_profit = int(df["profit"].sum())
filtered_records = df.to_dict("records")
win_rate = get_win_rate(filtered_records)
best_idx = df["profit"].idxmax()
best_stock = df.loc[best_idx, "stock_name"]
top_broker_series = df.groupby("broker")["profit"].sum()
top_broker = top_broker_series.idxmax() if not top_broker_series.empty else "-"

col1, col2, col3, col4 = st.columns(4)
col1.metric("💰 총 누적 수익", format_krw(total_profit))
col2.metric("🎯 승률", f"{win_rate:.1f}%")
col3.metric("🏆 최고 수익 종목", best_stock)
col4.metric("🏦 최다 이용 증권사", top_broker)

st.divider()

# 월별 수익 막대 차트
st.subheader("📊 월별 수익")
available_years = sorted(df["year"].unique(), reverse=True)
selected_year = st.selectbox("연도 선택", available_years, index=0)

all_months = pd.DataFrame({"월번호": range(1, 13)})
monthly_grouped = (
    df[df["year"] == selected_year]
    .groupby("month")["profit"]
    .sum()
    .reset_index()
    .rename(columns={"month": "월번호", "profit": "수익"})
)
monthly = all_months.merge(monthly_grouped, on="월번호", how="left").fillna({"수익": 0})
monthly["수익"] = monthly["수익"].astype(int)
monthly["월"] = monthly["월번호"].apply(lambda m: f"{m}월")
monthly["색상"] = monthly["수익"].apply(lambda x: "수익" if x >= 0 else "손실")

fig_monthly = px.bar(
    monthly,
    x="월",
    y="수익",
    color="색상",
    color_discrete_map=PROFIT_COLORS,
    title=f"{selected_year}년 월별 수익",
    category_orders={"월": [f"{m}월" for m in range(1, 13)]},
)
fig_monthly.update_layout(yaxis_tickformat=",", showlegend=False)
st.plotly_chart(fig_monthly, use_container_width=True)

st.divider()

# 증권사별 / 청약방식별 비교
col_a, col_b = st.columns(2)

with col_a:
    st.subheader("🏦 증권사별 수익")
    broker_df = df.groupby("broker")["profit"].sum().reset_index()
    broker_df.columns = ["증권사", "수익"]
    fig_broker = px.pie(
        broker_df,
        names="증권사",
        values="수익",
        title="증권사별 총수익 비중",
        hole=0.35,
    )
    st.plotly_chart(fig_broker, use_container_width=True)

with col_b:
    st.subheader("📋 청약방식별 수익")
    sub_df = df.groupby("sub_type")["profit"].sum().reset_index()
    sub_df.columns = ["청약방식", "수익"]
    fig_sub = px.bar(
        sub_df,
        x="청약방식",
        y="수익",
        color="청약방식",
        color_discrete_map=SUB_TYPE_COLORS,
        title="청약방식별 총수익",
    )
    fig_sub.update_layout(yaxis_tickformat=",", showlegend=False)
    st.plotly_chart(fig_sub, use_container_width=True)

st.divider()

# 누적 수익 라인 차트
st.subheader("📈 누적 수익 추이")
df_sorted = df.sort_values("date").copy()
df_sorted["누적수익"] = df_sorted["profit"].cumsum()
df_sorted["종목"] = df_sorted["stock_name"]

fig_cum = px.line(
    df_sorted,
    x="date",
    y="누적수익",
    markers=True,
    hover_data={"종목": True, "누적수익": ":,"},
    title="전체 기간 누적 수익",
    labels={"date": "날짜", "누적수익": "누적 수익 (원)"},
)
fig_cum.update_xaxes(tickformat="%m월 %d일", tickangle=-45)
fig_cum.update_layout(yaxis_tickformat=",", hovermode="x unified")
st.plotly_chart(fig_cum, use_container_width=True)

st.divider()

# 분기별 성과 차트
st.subheader("📅 분기별 성과")
df["분기"] = df["date"].dt.quarter.map({1: "Q1", 2: "Q2", 3: "Q3", 4: "Q4"})
quarterly = (
    df.groupby(["year", "분기"])["profit"]
    .sum()
    .reset_index()
    .rename(columns={"year": "연도", "profit": "수익"})
)
quarterly["연도"] = quarterly["연도"].astype(str)

fig_q = px.bar(
    quarterly,
    x="분기",
    y="수익",
    color="연도",
    barmode="group",
    title="연도별 분기 수익 비교",
    category_orders={"분기": ["Q1", "Q2", "Q3", "Q4"]},
)
fig_q.update_layout(yaxis_tickformat=",")
st.plotly_chart(fig_q, use_container_width=True)
