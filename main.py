"""
어제의 박스오피스 - Streamlit 앱
--------------------------------
KOBIS(영화진흥위원회) 오픈API의 '일별 박스오피스' 결과를
어제 날짜(한국 시간 기준) 기준으로 보여주는 앱입니다.

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
st.set_page_config(page_title="어제의 박스오피스", page_icon="🎬", layout="wide")

KOBIS_URL = "https://www.kobis.or.kr/kobisopenapi/webservice/rest/boxoffice/searchDailyBoxOfficeList.json"


# -----------------------------
# 2. '어제' 날짜를 한국 시간(KST) 기준으로 계산하기
#    -> 배포 서버의 시계가 한국 시간이 아닐 수 있으므로,
#       무조건 Asia/Seoul 시간대를 기준으로 계산해야 합니다.
# -----------------------------
def get_yesterday_kst() -> str:
    now_kst = datetime.now(ZoneInfo("Asia/Seoul"))
    yesterday_kst = now_kst - timedelta(days=1)
    return yesterday_kst.strftime("%Y%m%d")  # KOBIS가 원하는 형식: yyyymmdd (8자리)


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
# 5. 조회할 날짜(어제) 계산
# -----------------------------
target_dt = get_yesterday_kst()
target_dt_pretty = f"{target_dt[0:4]}년 {target_dt[4:6]}월 {target_dt[6:8]}일"

st.title("🎬 어제의 박스오피스")
st.caption(f"조회 날짜: {target_dt_pretty} (한국 시간 기준 어제)")


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
        f"{target_dt_pretty} 박스오피스 데이터가 비어 있습니다.\n"
        "해당 날짜의 집계가 아직 완료되지 않았거나, KOBIS 서버 점검 중일 수 있어요.\n"
        "잠시 후 다시 시도해주세요."
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
card1.metric("어제 관객수", f"{int(top_movie['audiCnt']):,}명")
card2.metric("누적 관객수", f"{int(top_movie['audiAcc']):,}명")
card3.metric("스크린수", f"{int(top_movie['scrnCnt']):,}개")

st.divider()


# -----------------------------
# 9. 전체 순위 표
#    -> 요청하신 6개 항목만 골라서, 한글 이름으로 바꿔 보여줍니다.
# -----------------------------
st.subheader("📋 전체 순위")

table_df = df[["rank", "movieNm", "openDt", "audiCnt", "audiAcc", "scrnCnt"]].copy()
table_df.columns = ["순위", "영화명", "개봉일", "관객수", "누적관객수", "스크린수"]

st.dataframe(table_df, use_container_width=True, hide_index=True)

st.divider()


# -----------------------------
# 10. 관객수 상위 5편 - 막대그래프
# -----------------------------
st.subheader("📊 관객수 상위 5편")

top5_df = df.sort_values("audiCnt", ascending=False).head(5)
chart_data = top5_df.set_index("movieNm")["audiCnt"]

st.bar_chart(chart_data)
