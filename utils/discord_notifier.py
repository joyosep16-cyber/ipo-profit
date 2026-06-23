import logging
import os
from datetime import datetime, timezone

import requests

from utils.calculator import format_krw

logger = logging.getLogger(__name__)


def _webhook_url() -> str:
    url = os.getenv("DISCORD_WEBHOOK_URL", "")
    if not url:
        try:
            from database import get_setting
            url = get_setting("DISCORD_WEBHOOK_URL") or ""
        except Exception:
            pass
    return url


def _send(embed: dict) -> None:
    url = _webhook_url()
    if not url:
        logger.warning("DISCORD_WEBHOOK_URL이 설정되지 않아 알림을 건너뜁니다.")
        return
    try:
        resp = requests.post(url, json={"embeds": [embed]}, timeout=10)
        if resp.status_code not in (200, 204):
            logger.warning(f"Discord 웹훅 응답 오류: HTTP {resp.status_code} — {resp.text[:200]}")
    except Exception as e:
        logger.error(f"Discord 알림 전송 실패: {e}")




def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def send_record_added(record: dict) -> None:
    rr = record.get("return_rate")
    _send({
        "title": "🆕 새 공모주 추가",
        "color": 0x00B894,
        "fields": [
            {"name": "📌 종목", "value": record["stock_name"], "inline": True},
            {"name": "🏦 증권사", "value": record["broker"], "inline": True},
            {"name": "💰 공모가", "value": f"₩{record['ipo_price']:,}", "inline": True},
            {"name": "📋 청약방식", "value": record["sub_type"], "inline": True},
            {"name": "🎯 당첨여부", "value": record.get("sub_result", "당첨"), "inline": True},
            {"name": "📦 수량", "value": f"{record['quantity']}주", "inline": True},
            {"name": "💵 수익", "value": format_krw(record["profit"], signed=True), "inline": True},
            {"name": "📈 수익률", "value": f"{rr:.1f}%" if rr is not None else "-", "inline": True},
            {"name": "📅 날짜", "value": str(record["date"]), "inline": True},
        ],
        "timestamp": _now_iso(),
    })


def send_record_updated(old: dict, new: dict) -> None:
    _send({
        "title": "✏️ 공모주 수정",
        "color": 0x0984E3,
        "fields": [
            {"name": "📌 종목", "value": new["stock_name"], "inline": True},
            {"name": "📅 날짜", "value": str(new["date"]), "inline": True},
            {"name": "🎯 당첨여부", "value": new.get("sub_result", "당첨"), "inline": True},
            {"name": "💵 수익 (이전)", "value": format_krw(old["profit"], signed=True), "inline": True},
            {"name": "💵 수익 (변경)", "value": format_krw(new["profit"], signed=True), "inline": True},
        ],
        "timestamp": _now_iso(),
    })


def send_record_deleted(record: dict) -> None:
    _send({
        "title": "🗑️ 공모주 삭제",
        "color": 0xD63031,
        "fields": [
            {"name": "📌 종목", "value": record["stock_name"], "inline": True},
            {"name": "🏦 증권사", "value": record["broker"], "inline": True},
            {"name": "🎯 당첨여부", "value": record.get("sub_result", "당첨"), "inline": True},
            {"name": "💵 수익", "value": format_krw(record["profit"], signed=True), "inline": True},
            {"name": "📅 날짜", "value": str(record["date"]), "inline": True},
        ],
        "timestamp": _now_iso(),
    })


def send_high_return_alert(record: dict) -> None:
    rr = record.get("return_rate")
    if rr is None:
        return
    _send({
        "title": "🎉 고수익 달성!",
        "color": 0xFDCB6E,
        "description": f"**{record['stock_name']}** 에서 **{rr:.1f}%** 수익률 달성!",
        "fields": [
            {"name": "📌 종목", "value": record["stock_name"], "inline": True},
            {"name": "🏦 증권사", "value": record["broker"], "inline": True},
            {"name": "💵 수익", "value": format_krw(record["profit"], signed=True), "inline": True},
            {"name": "📈 수익률", "value": f"{rr:.1f}%", "inline": True},
        ],
        "timestamp": _now_iso(),
    })


def send_monthly_summary(year: int, month: int, stats: dict) -> None:
    if stats["count"] == 0:
        return
    best = stats.get("best_record")
    best_str = (
        f"{best['stock_name']} ({format_krw(best['profit'], signed=True)})" if best else "-"
    )
    _send({
        "title": f"📊 {year}년 {month}월 공모주 수익 요약",
        "color": 0x6C5CE7,
        "fields": [
            {"name": "📦 청약 종목 수", "value": f"{stats['count']}개", "inline": True},
            {"name": "💵 총 수익", "value": format_krw(stats["total_profit"], signed=True), "inline": True},
            {"name": "🏆 최고 수익 종목", "value": best_str, "inline": False},
        ],
        "timestamp": _now_iso(),
    })


def send_watchlist_reminder(item: dict) -> None:
    _send({
        "title": "⏰ 청약 마감 내일!",
        "color": 0xFFA07A,
        "fields": [
            {"name": "📌 종목",     "value": item["stock_name"],                                           "inline": True},
            {"name": "🏦 증권사",   "value": item.get("broker") or "-",                                   "inline": True},
            {"name": "📅 청약 마감", "value": str(item["sub_end"]) if item.get("sub_end") else "-",        "inline": True},
            {"name": "💰 공모가",   "value": f"₩{item['ipo_price']:,}" if item.get("ipo_price") else "-", "inline": True},
        ],
        "timestamp": _now_iso(),
    })


def send_watchlist_missed(item: dict) -> None:
    _send({
        "title": "❌ 청약 미신청 처리됨",
        "color": 0x808080,
        "fields": [
            {"name": "📌 종목",     "value": item["stock_name"],                                    "inline": True},
            {"name": "🏦 증권사",   "value": item.get("broker") or "-",                            "inline": True},
            {"name": "📅 청약 마감", "value": str(item["sub_end"]) if item.get("sub_end") else "-", "inline": True},
        ],
        "timestamp": _now_iso(),
    })


def send_listing_day_alert(item: dict) -> None:
    """청약 신청(청약완료)한 종목의 상장 당일 Discord 알림."""
    fields = [
        {"name": "📌 종목",   "value": item["stock_name"],                                          "inline": True},
        {"name": "🏦 증권사", "value": item.get("broker") or "-",                                   "inline": True},
        {"name": "🏛️ 상장일", "value": str(item["listing_date"]) if item.get("listing_date") else "-", "inline": True},
    ]
    if item.get("ipo_price"):
        fields.append({"name": "💰 공모가", "value": f"₩{item['ipo_price']:,}", "inline": True})
    if item.get("analysis_score") is not None:
        grade = item.get("analysis_grade") or ""
        fields.append({"name": "📊 분석점수", "value": f"{item['analysis_score']}점 {grade}".strip(), "inline": True})
    _send({
        "title": "🔔 오늘 상장! (청약 신청 종목)",
        "color": 0xE17055,
        "description": f"**{item['stock_name']}** 이(가) 오늘 상장합니다. 매도 타이밍을 확인하세요!",
        "fields": fields,
        "timestamp": _now_iso(),
    })


def send_listing_dday_alert(item: dict) -> None:
    """청약 신청(청약완료)한 종목의 상장 D-1(전날) Discord 미리 알림."""
    fields = [
        {"name": "📌 종목",   "value": item["stock_name"],                                          "inline": True},
        {"name": "🏦 증권사", "value": item.get("broker") or "-",                                   "inline": True},
        {"name": "🏛️ 상장일", "value": str(item["listing_date"]) if item.get("listing_date") else "-", "inline": True},
    ]
    if item.get("ipo_price"):
        fields.append({"name": "💰 공모가", "value": f"₩{item['ipo_price']:,}", "inline": True})
    if item.get("analysis_score") is not None:
        grade = item.get("analysis_grade") or ""
        fields.append({"name": "📊 분석점수", "value": f"{item['analysis_score']}점 {grade}".strip(), "inline": True})
    _send({
        "title": "⏳ 내일 상장! (청약 신청 종목) — D-1",
        "color": 0xFDCB6E,
        "description": f"**{item['stock_name']}** 이(가) 내일 상장합니다. 매도 계획을 미리 세워두세요!",
        "fields": fields,
        "timestamp": _now_iso(),
    })


def send_pending_holdings_summary(items: list) -> None:
    """청약 후 상장 대기 중(미상장)인 보유 종목 주간 요약 Discord 알림.

    items: _pending_listing_candidates() 중 상장일이 오늘 이후인 종목들(상장일 오름차순)."""
    if not items:
        return
    from utils.timeutil import today_kst
    today = today_kst()  # KST 기준
    lines = []
    for it in items:
        ld = it.get("listing_date")
        broker = it.get("broker") or "-"
        if ld:
            delta = (ld - today).days
            dday = "D-Day" if delta == 0 else f"D-{delta}"
            ld_str = ld.strftime("%m/%d")
        else:
            dday, ld_str = "-", "-"
        score = it.get("analysis_score")
        score_str = f" · {score}점" if score is not None else ""
        lines.append(f"• **{it['stock_name']}** ({broker}) — 상장 {ld_str} `{dday}`{score_str}")
    _send({
        "title": f"🗓️ 청약 후 상장 대기 종목 {len(items)}개",
        "color": 0x74B9FF,
        "description": "\n".join(lines),
        "footer": {"text": "매도가를 입력하면 목록에서 자동 제외됩니다."},
        "timestamp": _now_iso(),
    })


def send_app_started(public_url: str) -> None:
    _send({
        "title": "🚀 공모주 수익 관리 앱 시작",
        "color": 0x55EFC4,
        "description": "앱이 실행되었습니다. 아래 링크로 접속하세요.",
        "fields": [
            {"name": "🔗 접속 URL", "value": public_url, "inline": False},
        ],
        "timestamp": _now_iso(),
    })


# ── 공모주 수요예측 분석 점수 알림 (analyzer 엔진) ─────────────────────────────

_QUALITY_COLOR = {
    "🟢 일치":            0x00FF00,
    "🟡 DART 보정됨":     0xFF9900,
    "🔴 38 폴백(추정치)":  0xFF0000,
}


def _fmt_premium(premium) -> str:
    if premium is None:
        return "N/A (스팩/리츠)"
    sign = "+" if premium >= 0 else ""
    return f"{sign}{premium:.2f}%"


def _fmt_deposit_map(deposit_map: dict) -> str:
    if not deposit_map:
        return "-"
    lines = []
    for name, info in deposit_map.items():
        qty = info.get("min_qty", 10)
        dep = info.get("deposit", 0)
        est = info.get("estimated", True)
        qty_label = f"최소 {qty}주 추정" if est else f"최소 {qty}주"
        lines.append(f"🏢 {name} ({qty_label} / 증거금: {dep:,}원)")
    return "\n".join(lines)


def send_analysis_score(detail: dict, result: dict, metrics: dict) -> None:
    """공모주 수요예측 분석 점수 카드를 Discord 로 발송.

    detail: scraper.fetch_detail + merge_sources 결과
    result: evaluator.evaluate_ipo_score 결과
    metrics: evaluator.build_metrics 결과
    """
    name = detail.get("name", "-")
    total = result.get("total")
    is_spac = result.get("is_spac_reit", False)
    quality = detail.get("data_quality")
    warn = "" if metrics.get("raw_verified") else " ⚠️(추정치)"
    price = detail.get("confirmed_price")
    band_high = detail.get("band_high")

    # 확정공모가 + 밴드 표기
    if price and band_high:
        if price > band_high:
            price_str = f"{int(price):,}원 (밴드 초과 🔼)"
        elif price == band_high:
            price_str = f"{int(price):,}원 (상단 확정 ✅)"
        else:
            price_str = f"{int(price):,}원 (밴드 내)"
    elif price:
        price_str = f"{int(price):,}원"
    else:
        price_str = "-"

    fields = [
        {"name": "확정 공모가", "value": price_str, "inline": True},
        {"name": "기관 경쟁률", "value": f"{metrics['inst_competition']:,.2f} : 1{warn}", "inline": True},
        {"name": "의무보유확약", "value": f"{metrics['lockup_ratio']:.2f}%{warn}", "inline": True},
    ]

    if is_spac:
        title = f"ℹ️ [SPAC/리츠] {name} 수요예측 결과"
        color = result.get("color", 0x3498DB)
        desc = f"ℹ️ **{result.get('notice', '[SPAC/리츠] 기본 지표만 참고')}**"
        fields.append({"name": "장외 괴리율", "value": "N/A (스팩/리츠는 장외 거래 없음)", "inline": True})
        footer = "SPAC/리츠 — 점수 산정 대상 아님"
    else:
        title = f"🚨 [공모주 분석] {name} 수요예측 결과"
        color = _QUALITY_COLOR.get(quality, result.get("color", 0x00FF00))
        desc = (f"{result.get('emoji','')} **{result.get('verdict','')}** — {result.get('grade','')}\n"
                f"📌 {result.get('action','')}\n💰 {result.get('expected_return','')}")
        fields.append({"name": "유통가능규모", "value": f"약 {metrics['circulating_eok']:,.0f}억원", "inline": True})
        otc_str = "없음 (장외 -2)" if metrics.get("otc_missing") else _fmt_premium(metrics["otc_premium"])
        fields.append({"name": "장외 괴리율", "value": otc_str, "inline": True})
        footer = f"가이드라인 총점: {total}점 | {result.get('expected_return','')}"

    fields.append({"name": "상장 예정일", "value": str(detail.get("listing_date") or "-"), "inline": True})
    fields.append({"name": "🏢 주관사별 최소 증거금",
                   "value": _fmt_deposit_map(metrics.get("deposit_map", {})), "inline": False})
    if quality:
        fields.append({"name": "데이터 신뢰도", "value": quality, "inline": True})

    _send({
        "title": title,
        "description": desc,
        "color": color,
        "fields": fields,
        "footer": {"text": footer},
        "timestamp": _now_iso(),
    })
