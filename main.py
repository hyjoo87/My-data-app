"""
어제의 박스오피스 (KOBIS 일별 박스오피스 API)

- 인증키는 코드에 쓰지 않고 Streamlit의 비밀 금고(secrets)에서 꺼내 씁니다.
- 조회 날짜는 '한국 시간 기준 어제'를 자동으로 계산합니다.
- 같은 날짜를 다시 조회하면 1시간 동안은 API를 다시 부르지 않습니다.
"""

import datetime as dt

import pandas as pd
import requests
import streamlit as st

# ─────────────────────────────────────────────────────────────
# 1. 기본 설정값
# ─────────────────────────────────────────────────────────────

# KOBIS 일별 박스오피스 요청 주소 (공식 문서에서 그대로 가져온 값)
API_URL = (
    "https://www.kobis.or.kr/kobisopenapi/webservice/rest"
    "/boxoffice/searchDailyBoxOfficeList.json"
)

# 한국 표준시(KST)는 UTC보다 9시간 빠릅니다.
# 배포 서버(스트림릿 클라우드)의 시계는 보통 UTC라서,
# 서버 시계를 그대로 믿지 말고 여기서 직접 9시간을 더해 줍니다.
KST = dt.timezone(dt.timedelta(hours=9))

# 캐시(결과를 잠깐 기억해 두는 것)를 유지할 시간 = 1시간 = 3600초
CACHE_TTL_SECONDS = 3600

# 화면 기본 설정. 코드 맨 위쪽에서 한 번만 호출해야 합니다.
st.set_page_config(page_title="어제의 박스오피스", page_icon="🎬", layout="wide")


# ─────────────────────────────────────────────────────────────
# 2. 작은 도우미 함수들
# ─────────────────────────────────────────────────────────────

def get_yesterday_kst() -> str:
    """한국 시간 기준 '어제' 날짜를 yyyymmdd 형태의 문자열로 돌려줍니다.

    오늘 자 집계는 아직 나오지 않기 때문에 항상 하루 전을 조회합니다.
    """
    now_kst = dt.datetime.now(KST)          # 지금 시각을 한국 시간으로
    yesterday = now_kst - dt.timedelta(days=1)   # 하루 빼기
    return yesterday.strftime("%Y%m%d")     # 예: "20260916"


def format_date_for_human(yyyymmdd: str) -> str:
    """'20260916' 처럼 붙어 있는 날짜를 '2026-09-16' 로 보기 좋게 바꿉니다."""
    return f"{yyyymmdd[0:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}"


def to_int(value) -> int:
    """문자열로 오는 숫자를 진짜 정수로 바꿉니다.

    KOBIS는 관객수·스크린수 같은 값을 모두 문자열("1234")로 보내줍니다.
    이대로 두면 정렬이 글자 순서로 되어 버리고 그래프도 그릴 수 없습니다.
    쉼표가 섞여 있거나 값이 비어 있는 경우도 있어 안전하게 처리합니다.
    """
    try:
        return int(str(value).replace(",", "").strip())
    except (ValueError, AttributeError, TypeError):
        return 0


def get_api_key():
    """비밀 금고에서 인증키를 꺼냅니다. 없으면 None을 돌려줍니다.

    스트림릿 클라우드에서는 앱 설정의 Secrets 칸에 아래처럼 적어 둡니다.
        KOBIS_KEY = "발급받은_인증키"
    """
    try:
        return st.secrets["KOBIS_KEY"]
    except Exception:
        # 금고 자체가 없거나 KOBIS_KEY 항목이 없을 때
        return None


# ─────────────────────────────────────────────────────────────
# 3. API 호출 (결과를 1시간 동안 기억)
# ─────────────────────────────────────────────────────────────

# @st.cache_data 는 "함수에 넣은 값이 똑같으면 실행하지 말고
# 저장해 둔 결과를 그대로 다시 써라"는 뜻입니다.
# ttl=3600 이므로 1시간이 지나면 저장해 둔 결과를 버리고 다시 불러옵니다.
@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def fetch_box_office(target_dt: str, api_key: str) -> dict:
    """KOBIS에 요청을 보내고 응답을 파이썬 딕셔너리로 돌려줍니다.

    통신 자체가 실패하면 예외(에러)가 발생하고, 그 처리는 부르는 쪽에서 합니다.
    """
    response = requests.get(
        API_URL,
        params={"key": api_key, "targetDt": target_dt},
        timeout=10,  # 10초 안에 응답이 없으면 포기
    )
    response.raise_for_status()  # 404, 500 같은 오류 상태코드면 예외 발생
    return response.json()       # JSON 글자를 파이썬 자료형으로 변환


def build_dataframe(movie_list: list) -> pd.DataFrame:
    """영화 목록(리스트)을 표(DataFrame)로 정리합니다.

    이 단계에서 문자열 숫자를 전부 정수로 바꿔 둡니다.
    """
    rows = []
    for movie in movie_list:
        rows.append(
            {
                "순위": to_int(movie.get("rank")),
                "영화명": movie.get("movieNm", ""),
                "개봉일": movie.get("openDt", ""),
                "관객수": to_int(movie.get("audiCnt")),
                "누적관객": to_int(movie.get("audiAcc")),
                "스크린수": to_int(movie.get("scrnCnt")),
                "상영횟수": to_int(movie.get("showCnt")),
                "전일대비": to_int(movie.get("rankInten")),
            }
        )

    df = pd.DataFrame(rows)
    # 숫자로 바꿔 두었으므로 순위대로 정확히 정렬됩니다.
    return df.sort_values("순위").reset_index(drop=True)


# ─────────────────────────────────────────────────────────────
# 4. 화면 그리기
# ─────────────────────────────────────────────────────────────

st.title("🎬 어제의 박스오피스")

target_dt = get_yesterday_kst()
st.caption(
    f"조회 기준일: **{format_date_for_human(target_dt)}** (한국 시간 기준 어제) · "
    "자료 출처: 영화진흥위원회 KOBIS"
)

api_key = get_api_key()

# ── 상황 1) 인증키가 아예 없을 때 ────────────────────────────
if not api_key:
    st.error("인증키를 찾지 못했습니다.")
    st.markdown(
        """
**이렇게 확인해 보세요**

1. 스트림릿 클라우드 앱 화면에서 **Settings → Secrets** 를 엽니다.
2. 아래 한 줄을 적고 저장합니다. 따옴표까지 그대로 필요합니다.

```toml
KOBIS_KEY = "발급받은_인증키"
```

3. 항목 이름의 철자가 `KOBIS_KEY` 가 맞는지 확인합니다. 대소문자를 구분합니다.
4. 저장한 뒤 앱을 다시 실행(Reboot)합니다.

컴퓨터에서 직접 실행 중이라면 프로젝트 폴더 안에
`.streamlit/secrets.toml` 파일을 만들고 같은 내용을 적으면 됩니다.
"""
    )
    st.stop()  # 여기서 멈춥니다. 아래 코드는 실행되지 않습니다.

# ── API 호출 ────────────────────────────────────────────────
try:
    with st.spinner("박스오피스를 불러오는 중입니다..."):
        data = fetch_box_office(target_dt, api_key)

except requests.exceptions.Timeout:
    st.error("KOBIS 서버의 응답이 너무 느립니다.")
    st.markdown(
        "- 잠시 뒤 아래 **다시 불러오기** 버튼을 눌러 주세요.\n"
        "- 계속 같은 증상이면 KOBIS 서버 점검 중일 수 있습니다."
    )
    if st.button("다시 불러오기"):
        st.cache_data.clear()
        st.rerun()
    st.stop()

except requests.exceptions.RequestException as error:
    st.error("KOBIS 서버에 연결하지 못했습니다.")
    st.markdown(
        "**이렇게 확인해 보세요**\n"
        "- 인터넷 연결 상태를 확인합니다.\n"
        "- KOBIS 사이트가 점검 중인지 확인합니다.\n"
        "- 잠시 뒤 다시 시도합니다."
    )
    st.caption(f"자세한 내용: {error}")
    st.stop()

except ValueError:
    # 응답이 JSON 모양이 아닐 때 (예: 점검 안내 HTML 페이지가 온 경우)
    st.error("서버가 보낸 응답을 읽을 수 없습니다.")
    st.markdown(
        "- 요청 주소가 올바른지 확인합니다.\n"
        "- KOBIS 서버 점검 중일 수 있으니 잠시 뒤 다시 시도합니다."
    )
    st.stop()

# ── 상황 2) 오류 상자(faultInfo)가 왔을 때 ───────────────────
# 인증키가 틀려도 상태코드는 200으로 오기 때문에 이 검사가 꼭 필요합니다.
if "faultInfo" in data:
    fault = data.get("faultInfo", {})
    st.error("KOBIS가 오류를 돌려주었습니다.")
    st.markdown(
        f"""
**서버가 알려준 내용**
- 오류 메시지: `{fault.get("message", "내용 없음")}`
- 오류 코드: `{fault.get("errorCode", "내용 없음")}`

**이렇게 확인해 보세요**

1. 인증키가 정확한지 확인합니다. 앞뒤에 빈칸이나 따옴표가 섞이지 않았는지 봅니다.
2. KOBIS 홈페이지에서 그 키가 아직 살아 있는지(정지·만료되지 않았는지) 확인합니다.
3. 하루 요청 한도를 넘지 않았는지 확인합니다.
4. 키를 새로 발급받았다면 Secrets 값을 바꾸고 앱을 다시 실행합니다.
"""
    )
    st.stop()

# ── 상황 3) 영화 목록이 비어서 왔을 때 ───────────────────────
movie_list = data.get("boxOfficeResult", {}).get("dailyBoxOfficeList", [])

if not movie_list:
    st.warning(f"{format_date_for_human(target_dt)} 자 박스오피스 자료가 비어 있습니다.")
    st.markdown(
        """
**이렇게 확인해 보세요**

1. 집계가 아직 끝나지 않았을 수 있습니다. KOBIS 자료는 보통 오전 중에 갱신됩니다.
   조금 뒤에 다시 열어 보세요.
2. 날짜가 너무 과거이거나 미래는 아닌지 확인합니다.
3. KOBIS 홈페이지에서 같은 날짜의 자료가 실제로 있는지 확인합니다.
"""
    )
    if st.button("다시 불러오기"):
        st.cache_data.clear()
        st.rerun()
    st.stop()

# ── 정상적으로 자료를 받은 경우 ──────────────────────────────
df = build_dataframe(movie_list)

# (1) 1위 영화를 지표 카드 세 장으로 크게 보여 주기
top_movie = df.iloc[0]  # 표의 첫 번째 줄 = 1위

st.subheader(f"🥇 1위 · {top_movie['영화명']}")

col1, col2, col3 = st.columns(3)  # 화면을 세 칸으로 나눕니다
col1.metric("어제 관객수", f"{top_movie['관객수']:,}명")
col2.metric("누적 관객수", f"{top_movie['누적관객']:,}명")
col3.metric("스크린수", f"{top_movie['스크린수']:,}개")

st.divider()

# (2) 관객수 상위 5편 막대그래프
st.subheader("📊 관객수 상위 5편")

top5 = df.nlargest(5, "관객수")  # 숫자로 바꿔 두었기 때문에 제대로 동작합니다
chart_data = top5.set_index("영화명")[["관객수"]]
st.bar_chart(chart_data)

st.divider()

# (3) 전체 표
st.subheader("📋 박스오피스 전체 순위")

table = df[["순위", "영화명", "개봉일", "관객수", "누적관객", "스크린수"]]

st.dataframe(
    table,
    hide_index=True,
    use_container_width=True,
    column_config={
        # 숫자 칸은 쉼표를 찍어 읽기 좋게 표시합니다
        "관객수": st.column_config.NumberColumn("관객수", format="%,d"),
        "누적관객": st.column_config.NumberColumn("누적관객", format="%,d"),
        "스크린수": st.column_config.NumberColumn("스크린수", format="%,d"),
    },
)

# 새로고침 버튼: 저장해 둔 결과를 버리고 다시 불러옵니다
if st.button("🔄 최신 자료로 다시 불러오기"):
    st.cache_data.clear()
    st.rerun()

st.caption("불러온 결과는 1시간 동안 저장되어, 같은 날짜는 다시 요청하지 않습니다.")
