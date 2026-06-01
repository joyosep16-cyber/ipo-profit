import os

import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(
    page_title="공모주 수익 관리",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

from database import init_db
from utils.init_app import setup

# 핫리로드 시 session_state가 초기화되므로, 코드 변경 후에도 마이그레이션이 반드시 실행됨
# (@st.cache_resource는 핫리로드에도 보존되므로 setup() 내부 init_db()에만 의존하면 안 됨)
if "db_initialized" not in st.session_state:
    init_db()
    st.session_state["db_initialized"] = True


@st.cache_resource
def _start_ngrok_for_token(token: str) -> tuple[str | None, str | None]:
    """(public_url, error_message) 반환. 기존 세션 재사용 또는 정리 후 재연결."""
    if not token:
        return None, None
    try:
        from pyngrok import conf, ngrok
        import atexit
        from utils.init_app import _cleanup_ngrok

        conf.get_default().auth_token = token
        atexit.register(_cleanup_ngrok)

        # 로컬 API(4040)로 이미 살아있는 터널 재사용
        try:
            import requests as _req
            resp = _req.get("http://localhost:4040/api/tunnels", timeout=2)
            if resp.ok:
                for t in resp.json().get("tunnels", []):
                    if t.get("proto") == "https":
                        return t["public_url"], None
        except Exception:
            pass

        tunnels = ngrok.get_tunnels()
        if tunnels:
            return tunnels[0].public_url, None

        ngrok.kill()
        tunnel = ngrok.connect(8501)
        return tunnel.public_url, None
    except Exception as e:
        import re
        m = re.search(r"'(https://[^\s']+\.ngrok[^\s']*)'", str(e))
        if m:
            return m.group(1), None
        return None, str(e)


def _get_ngrok_token() -> str:
    token = os.getenv("NGROK_AUTH_TOKEN", "").strip()
    if not token:
        try:
            from database import get_setting
            token = get_setting("NGROK_AUTH_TOKEN", "").strip()
            if token:
                os.environ["NGROK_AUTH_TOKEN"] = token
        except Exception:
            pass
    return token


app_state = setup()
public_url = app_state.get("public_url")
ngrok_error = None

if not public_url:
    current_token = _get_ngrok_token()
    public_url, ngrok_error = _start_ngrok_for_token(current_token)

# 사이드바 - 접속 URL & QR
with st.sidebar:
    st.markdown("## 📈 공모주 수익 관리")
    st.divider()

    if public_url:
        st.markdown("**🔗 외부 접속 URL**")
        st.markdown(f"[{public_url}]({public_url})")
        try:
            import qrcode
            from io import BytesIO

            qr = qrcode.make(public_url)
            buf = BytesIO()
            qr.save(buf, format="PNG")
            st.image(buf.getvalue(), caption="QR 스캔으로 모바일 접속", width=150)
        except Exception:
            pass
    else:
        st.markdown("**🔗 외부 접속 URL**")
        if _get_ngrok_token():
            if ngrok_error:
                st.error(f"ngrok 연결 실패:\n{ngrok_error}")
            else:
                st.caption("ngrok 연결 중 오류 발생.")
            if st.button("🔄 재연결 시도", key="sidebar_ngrok_reconnect"):
                _start_ngrok_for_token.clear()
                st.rerun()
        else:
            st.caption("⚙️ 설정에서 ngrok 토큰을 입력하면 외부 접속 URL이 생성됩니다.")

    st.divider()
    st.caption("© 공모주 수익 관리 앱")

# 달력 UI 한국어 표시 (MutationObserver로 react-datepicker 번역)
components.html("""
<script>
(function() {
    if (window.parent.__koCalendarInstalled) return;
    window.parent.__koCalendarInstalled = true;
    const MONTHS = {
        "January":"1월","February":"2월","March":"3월","April":"4월",
        "May":"5월","June":"6월","July":"7월","August":"8월",
        "September":"9월","October":"10월","November":"11월","December":"12월"
    };
    const DAYS = {"Su":"일","Mo":"월","Tu":"화","We":"수","Th":"목","Fr":"금","Sa":"토"};
    function translate() {
        const doc = window.parent.document;
        doc.querySelectorAll('.react-datepicker__current-month').forEach(el => {
            let t = el.textContent;
            for (const [en, ko] of Object.entries(MONTHS)) {
                if (t.includes(en)) { el.textContent = t.replace(en, ko); break; }
            }
        });
        doc.querySelectorAll('.react-datepicker__day-name').forEach(el => {
            const t = el.textContent.trim();
            if (DAYS[t]) el.textContent = DAYS[t];
        });
    }
    new MutationObserver(translate)
        .observe(window.parent.document.body, {childList:true, subtree:true});
})();
</script>
""", height=0, scrolling=False)

pg = st.navigation(
    {
        "메뉴": [
            st.Page("pages/watchlist.py", title="관심 목록",  icon="⭐"),
            st.Page("pages/analysis.py",  title="공모주 분석", icon="🔍"),
            st.Page("pages/input.py",     title="데이터 입력", icon="✏️"),
            st.Page("pages/home.py",      title="수익 현황",  icon="📊", default=True),
            st.Page("pages/charts.py",    title="통계/차트",  icon="📉"),
            st.Page("pages/yearly.py",    title="연도별 요약", icon="📅"),
            st.Page("pages/settings.py",  title="설정",       icon="⚙️"),
        ]
    }
)

pg.run()
