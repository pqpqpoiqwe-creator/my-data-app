"""
날짜별 박스오피스 - Streamlit 앱
--------------------------------
KOBIS(영화진흥위원회) 오픈API의 '일별 박스오피스' 결과를
달력에서 고른 날짜(최대 어제, 한국 시간 기준) 기준으로 보여주는 앱입니다.

* 인증키는 코드에 직접 쓰지 않고, Streamlit의 secrets(비밀 금고)에서 불러옵니다.
  -> 로컬에서 테스트할 땐 .streamlit/secrets.toml 파일에
        KOBIS_KEY = "여기에 실제 발급받은 키"
     를 적어두고, Streamlit Cloud에 배포할 때는
     앱 설정(Settings) > Secrets 메뉴에 같은 내용을 붙여넣으면 됩니다.
"""

import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


# -----------------------------
# 1. 페이지 기본 설정
# -----------------------------
st.set_page_config(page_title="날짜별 박스오피스", page_icon="🎬", layout="wide")

KOBIS_URL = "https://www.kobis.or.kr/kobisopenapi/webservice/rest/boxoffice/searchDailyBoxOfficeList.json"


# -----------------------------
# 2. '어제' 날짜를 한국 시간(KST) 기준으로 계산하기
#    -> 배포 서버의 시계가 한국 시간이 아닐 수 있으므로,
#       무조건 Asia/Seoul 시간대를 기준으로 계산해야 합니다.
#    -> 오늘 건 아직 집계 전이라, 달력에서 고를 수 있는
#       가장 늦은 날짜는 '어제'까지로 제한합니다.
# -----------------------------
def get_yesterday_kst_date():
    now_kst = datetime.now(ZoneInfo("Asia/Seoul"))
    return (now_kst - timedelta(days=1)).date()


# -----------------------------
# 3. KOBIS API 호출하기
#    -> st.cache_data(ttl=3600)을 붙이면,
#       같은 날짜(target_dt)로 다시 요청이 와도
#       1시간(3600초) 동안은 API를 다시 부르지 않고
#       저장해둔 결과를 그대로 재사용합니다.
# -----------------------------
@st.cache_data(ttl=3600, show_spinner="박스오피스 정보를 불러오는 중...")
def fetch_box_office(target_dt: str, api_key: str) -> dict:
    params = {"key": api_key, "targetDt": target_dt}
    response = requests.get(KOBIS_URL, params=params, timeout=10)
    response.raise_for_status()  # 상태코드가 200이 아니면 여기서 예외 발생
    return response.json()


# -----------------------------
# 4. 인증키 확인
#    -> secrets에 KOBIS_KEY가 없으면 화면에 안내만 하고 앱을 멈춥니다.
# -----------------------------
api_key = st.secrets.get("KOBIS_KEY")

if not api_key:
    st.error(
        "인증키를 찾을 수 없습니다. Streamlit Cloud의 'Settings > Secrets'에\n"
        "KOBIS_KEY = \"발급받은 인증키\" 형식으로 등록되어 있는지 확인해주세요."
    )
    st.stop()  # 아래 코드를 실행하지 않고 여기서 중단


# -----------------------------
# 5. 조회할 날짜 고르기 (달력)
#    -> 고를 수 있는 가장 늦은 날짜는 '어제'까지입니다. (오늘 건 아직 집계 전)
# -----------------------------
st.title("🎬 날짜별 박스오피스")

max_date = get_yesterday_kst_date()

selected_date = st.date_input(
    "조회할 날짜를 선택하세요",
    value=max_date,       # 처음 열었을 때는 어제 날짜가 기본으로 선택됨
    max_value=max_date,   # 오늘/미래 날짜는 선택할 수 없음
)

target_dt = selected_date.strftime("%Y%m%d")  # KOBIS가 원하는 형식: yyyymmdd (8자리)
target_dt_pretty = selected_date.strftime("%Y년 %m월 %d일")

st.caption(f"조회 날짜: {target_dt_pretty}")


# -----------------------------
# 6. API 호출 + 오류 처리
#    - 네트워크/서버 문제로 요청 자체가 실패하는 경우
#    - 인증키가 틀려서 faultInfo 상자가 오는 경우 (상태코드는 200)
#    - 영화 목록이 비어 있는 경우 (아직 집계가 안 됐거나 서버 점검 등)
# -----------------------------
try:
    raw_data = fetch_box_office(target_dt, api_key)
except requests.exceptions.RequestException:
    st.error(
        "KOBIS 서버에 연결하지 못했습니다.\n"
        "잠시 후 다시 시도하거나, 인터넷 연결 상태 또는 KOBIS 서버 상태를 확인해주세요."
    )
    st.stop()

# faultInfo 상자가 있으면 인증키 문제일 가능성이 큽니다.
fault_info = raw_data.get("faultInfo")
if fault_info:
    fault_message = fault_info.get("message", "알 수 없는 오류")
    st.error(
        f"KOBIS API에서 오류를 반환했습니다: {fault_message}\n"
        "발급받은 인증키(KOBIS_KEY)가 정확한지, 아직 유효한지 확인해주세요."
    )
    st.stop()

box_office_result = raw_data.get("boxOfficeResult", {})
movie_list = box_office_result.get("dailyBoxOfficeList", [])

if not movie_list:
    st.warning(
        f"{target_dt_pretty} : 그날은 아직 집계 전입니다.\n"
        "(다른 날짜를 선택해보시거나, 잠시 후 다시 시도해주세요.)"
    )
    st.stop()


# -----------------------------
# 7. 데이터를 표(DataFrame)로 만들고, 문자열로 온 숫자를 실제 숫자로 변환
#    -> 이렇게 바꿔야 정렬(sort)이나 그래프에서 숫자 크기 비교가 정확해집니다.
# -----------------------------
df = pd.DataFrame(movie_list)

numeric_columns = ["rank", "rankInten", "audiCnt", "audiAcc", "scrnCnt", "showCnt"]
for col in numeric_columns:
    if col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")

# 순위(rank) 기준으로 오름차순 정렬 (1위부터)
df = df.sort_values("rank").reset_index(drop=True)


# -----------------------------
# 8. 1위 영화 - 지표 카드 3장으로 크게 보여주기
# -----------------------------
top_movie = df.iloc[0]

st.subheader(f"🥇 1위 - {top_movie['movieNm']}")

card1, card2, card3 = st.columns(3)
card1.metric("그날 관객수", f"{int(top_movie['audiCnt']):,}명")
card2.metric("누적 관객수", f"{int(top_movie['audiAcc']):,}명")
card3.metric("스크린수", f"{int(top_movie['scrnCnt']):,}개")

st.divider()


# -----------------------------
# 9. 전체 순위 표
#    -> 요청하신 6개 항목을 한글 이름으로 바꿔 보여줍니다.
#    -> rankInten(전날 대비 순위 증감)이 양수면 빨간 위 화살표(▲),
#       음수면 파란 아래 화살표(▼)를 순위 옆에 붙입니다.
#    -> 누적관객수(audiAcc)가 100만 명을 넘으면 영화명 옆에 🏆을 붙입니다.
#    -> 색깔 있는 화살표는 st.dataframe으로는 표현이 어려워서,
#       직접 HTML 표를 만들어 st.markdown으로 보여줍니다.
# -----------------------------
st.subheader("📋 전체 순위")

MILLION = 1_000_000  # 100만 명 기준값


def format_rank_change(inten: int) -> str:
    if pd.isna(inten) or inten == 0:
        return "-"
    if inten > 0:
        return f'<span style="color:red;">▲{int(inten)}</span>'
    return f'<span style="color:blue;">▼{abs(int(inten))}</span>'


def format_movie_name(name: str, audi_acc) -> str:
    if pd.notna(audi_acc) and audi_acc >= MILLION:
        return f"{name} 🏆"
    return name


table_df = df[["rank", "rankInten", "movieNm", "openDt", "audiCnt", "audiAcc", "scrnCnt"]].copy()
table_df["순위변동"] = table_df["rankInten"].apply(format_rank_change)
table_df["영화명"] = table_df.apply(lambda row: format_movie_name(row["movieNm"], row["audiAcc"]), axis=1)
table_df["관객수"] = table_df["audiCnt"].apply(lambda v: f"{int(v):,}" if pd.notna(v) else "-")
table_df["누적관객수"] = table_df["audiAcc"].apply(lambda v: f"{int(v):,}" if pd.notna(v) else "-")
table_df["스크린수"] = table_df["scrnCnt"].apply(lambda v: f"{int(v):,}" if pd.notna(v) else "-")
table_df["순위"] = table_df["rank"].apply(lambda v: int(v) if pd.notna(v) else "-")
table_df["개봉일"] = table_df["openDt"]

table_df = table_df[["순위", "순위변동", "영화명", "개봉일", "관객수", "누적관객수", "스크린수"]]

# to_html(escape=False)로 만들어야 위에서 넣은 <span> 태그(색깔)가 그대로 적용됩니다.
html_table = table_df.to_html(escape=False, index=False)
st.markdown(html_table, unsafe_allow_html=True)

st.divider()


# -----------------------------
# 10. 관객수 상위 5편 - 막대그래프
# -----------------------------
st.subheader("📊 관객수 상위 5편")

top5_df = df.sort_values("audiCnt", ascending=False).head(5)
chart_data = top5_df.set_index("movieNm")["audiCnt"]

st.bar_chart(chart_data)
