import streamlit as st
import pandas as pd
import numpy as np
import pydeck as pdk
import re
import os

# --- 1단계: r_eda.md 데이터 파싱 ---
def load_eda_data():
    eda_path = os.path.join(os.path.dirname(__file__), 'r_eda.md')
    try:
        with open(eda_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # 테이블 파싱 (정규표현식)
        table_pattern = re.compile(r'\| (.*?) \| (.*?) \| (.*?) \| (.*?) \| (.*?) \|')
        matches = table_pattern.findall(content)
        
        # 헤더와 구분선 제외
        data_rows = []
        for row in matches[2:]:
            dist = row[0].replace('**', '').strip()
            price = float(row[1].strip())
            hosp = int(row[2].strip())
            park = int(row[3].strip())
            crime = int(row[4].strip())
            data_rows.append([dist, price, hosp, park, crime])
            
        df = pd.DataFrame(data_rows, columns=['자치구', '평균매매가', '병원수', '공원수', '범죄건수'])
        return df
    except Exception as e:
        st.error(f"데이터 로드 실패: {e}")
        return pd.DataFrame()

# --- 2단계: 자치구 및 업무지구 좌표 정의 ---
DISTRICT_COORDS = {
    '종로구': (37.5730, 126.9794), '중구': (37.5636, 126.9976), '용산구': (37.5326, 126.9904),
    '성동구': (37.5633, 127.0371), '광진구': (37.5385, 127.0823), '동대문구': (37.5744, 127.0401),
    '중랑구': (37.6065, 127.0927), '성북구': (37.5891, 127.0167), '강북구': (37.6396, 127.0255),
    '도봉구': (37.6688, 127.0471), '노원구': (37.6544, 127.0563), '은평구': (37.6027, 126.9291),
    '서대문구': (37.5791, 126.9368), '마포구': (37.5662, 126.9016), '양천구': (37.5169, 126.8665),
    '강서구': (37.5509, 126.8496), '구로구': (37.4954, 126.8584), '금천구': (37.4568, 126.8953),
    '영등포구': (37.5263, 126.8962), '동작구': (37.5124, 126.9392), '관악구': (37.4784, 126.9515),
    '서초구': (37.4837, 127.0324), '강남구': (37.4959, 127.0664), '송파구': (37.5145, 127.1059),
    '강동구': (37.5302, 127.1238)
}

WORKPLACES = {
    '강남·서초': (37.4979, 127.0276),
    '여의도': (37.5215, 126.9242),
    '광화문·종로': (37.5704, 126.9769),
    '성수·마포': (37.5446, 127.0560) # 성수 기준
}

# --- 3단계: 통근 시간 계산 함수 ---
def calculate_commute(coord1, coord2):
    # 유클리디안 거리 (단순화: 1도 ≈ 111km)
    dist_km = np.sqrt((coord1[0]-coord2[0])**2 + (coord1[1]-coord2[1])**2) * 111
    time_min = dist_km * 3 # 1km 당 3분 가정
    return round(time_min, 1)

# --- Streamlit UI 시작 ---
st.set_page_config(page_title="신혼부부 서울 주거 최적지 추천", layout="wide")

st.title("💍 신혼부부 서울 아파트 전월세 최적 입지 추천")
st.markdown("`r_eda.md` 분석 결과를 바탕으로 개인형 맞춤 입지 랭킹을 제공합니다.")

# 데이터 로드
base_df = load_eda_data()
if base_df.empty:
    st.stop()

# 사이드바 설정
st.sidebar.header("⚙️ 분석 설정")

# Step 1. 가구 유형
family_type = st.sidebar.radio("Step 1. 가구 유형 선택", ["1인 직장", "맞벌이 부부"])

# Step 2. 직장 위치 & 통근 시간
st.sidebar.subheader("Step 2. 직장 위치 설정")
work_a = st.sidebar.selectbox("배우자 A 직장", list(WORKPLACES.keys()))
work_b = None
if family_type == "맞벌이 부부":
    work_b = st.sidebar.selectbox("배우자 B 직장", list(WORKPLACES.keys()), index=1)

max_commute = st.sidebar.select_slider("최대 통근 시간 (분)", options=[30, 45, 60], value=45)

# Step 3. 예산 필터
st.sidebar.subheader("Step 3. 예산 선택")
budget_filter = st.sidebar.radio("전세 예산 기준", ["전세 3억 이하", "전세 5억 이하", "제한 없음"])
st.sidebar.info("💡 실거래가 기반 프록시: 3억 이하(매매가 8억↓), 5억 이하(매매가 12억↓)")

# Step 4. 가중치 설정
st.sidebar.subheader("Step 4. 지표 가중치 (%)")
w_price = st.sidebar.slider("가격(낮을수록 점수↑)", 0, 100, 35)
w_commute = st.sidebar.slider("통근(짧을수록 점수↑)", 0, 100, 30)
w_infra = st.sidebar.slider("인프라(많을수록 점수↑)", 0, 100, 15)
w_safety = st.sidebar.slider("치안(범죄적을수록 점수↑)", 0, 100, 20)

# 가중치 정규화
total_w = w_price + w_commute + w_infra + w_safety
if total_w == 0:
    weights = [0.25, 0.25, 0.25, 0.25]
else:
    weights = [w_price/total_w, w_commute/total_w, w_infra/total_w, w_safety/total_w]

# --- 4단계: 데이터 처리 및 랭킹 산출 ---
df = base_df.copy()

# 통근 시간 계산
df['lat'] = df['자치구'].map(lambda x: DISTRICT_COORDS[x][0])
df['lon'] = df['자치구'].map(lambda x: DISTRICT_COORDS[x][1])

df['time_a'] = df.apply(lambda r: calculate_commute((r['lat'], r['lon']), WORKPLACES[work_a]), axis=1)
if family_type == "맞벌이 부부":
    df['time_b'] = df.apply(lambda r: calculate_commute((r['lat'], r['lon']), WORKPLACES[work_b]), axis=1)
    df['total_commute'] = df['time_a'] + df['time_b']
    # 필터: 각자 max_commute 이내
    df = df[(df['time_a'] <= max_commute) & (df['time_b'] <= max_commute)]
else:
    df['time_b'] = 0
    df['total_commute'] = df['time_a']
    df = df[df['time_a'] <= max_commute]

# 예산 필터링 (프록시 적용)
if budget_filter == "전세 3억 이하":
    df = df[df['평균매매가'] <= 8.0]
elif budget_filter == "전세 5억 이하":
    df = df[df['평균매매가'] <= 12.0]

if df.empty:
    st.warning("⚠️ 선택한 필터 조건(통근 시간/예산)을 만족하는 자치구가 없습니다. 조건을 완화해 보세요.")
    st.stop()

# 정규화 점수 산출
# 가격 (낮을수록 우수)
df['score_price'] = 1 - (df['평균매매가'] - df['평균매매가'].min()) / (df['평균매매가'].max() - df['평균매매가'].min() + 0.001)
# 통근 (짧을수록 우수)
df['score_commute'] = 1 - (df['total_commute'] - df['total_commute'].min()) / (df['total_commute'].max() - df['total_commute'].min() + 0.01)
# 인프라 (병원+공원, 높을수록 우수)
df['infra_sum'] = df['병원수'] + df['공원수'] * 50 # 공원 가중치 보정
df['score_infra'] = (df['infra_sum'] - df['infra_sum'].min()) / (df['infra_sum'].max() - df['infra_sum'].min() + 0.01)
# 치안 (범죄 낮을수록 우수)
df['score_safety'] = 1 - (df['범죄건수'] - df['범죄건수'].min()) / (df['범죄건수'].max() - df['범죄건수'].min() + 0.01)

# 종합 점수
df['total_score'] = (df['score_price'] * weights[0] + 
                     df['score_commute'] * weights[1] + 
                     df['score_infra'] * weights[2] + 
                     df['score_safety'] * weights[3])

# 별점 변환
def get_stars(score):
    n = int(round(score * 5))
    return "★" * max(1, n)

df['별점'] = df['total_score'].apply(get_stars)
top5 = df.sort_values('total_score', ascending=False).head(5)

# --- 5단계: 대시보드 출력 ---

# 상단 KPI
kpi1, kpi2, kpi3, kpi4 = st.columns(4)
kpi1.metric("후보 자치구", f"{len(df)}개")
kpi2.metric("TOP 1 추천", top5.iloc[0]['자치구'])
kpi3.metric("최고 점수", f"{top5.iloc[0]['total_score']:.2f}")
if family_type == "맞벌이 부부":
    avg_total = df['total_commute'].mean()
    kpi4.metric("평균 합산 통근", f"{avg_total:.1f}분")

# 지도 및 테이블 구성
col_map, col_table = st.columns([1.2, 1])

with col_map:
    st.subheader("📍 입지 추천 지도")
    
    # 지도 레이어
    # 1. 모든 후보
    view_state = pdk.ViewState(latitude=37.5665, longitude=126.9780, zoom=10.5, pitch=45)
    
    # 업무지구 포인트
    work_points = pd.DataFrame([
        {'name': k, 'lat': v[0], 'lon': v[1]} for k, v in WORKPLACES.items()
    ])
    
    layers = [
        # 업무지구 레이어 (파랑)
        pdk.Layer(
            "ScatterplotLayer",
            work_points,
            get_position="[lon, lat]",
            get_color="[0, 100, 255, 160]",
            get_radius=800,
            pickable=True,
        ),
        # TOP5 레이어 (노랑/강조)
        pdk.Layer(
            "ScatterplotLayer",
            top5,
            get_position="[lon, lat]",
            get_color="[255, 200, 0, 200]",
            get_radius=1200,
            pickable=True,
        ),
        # 기타 후보 (회색)
        pdk.Layer(
            "ScatterplotLayer",
            df[~df['자치구'].isin(top5['자치구'])],
            get_position="[lon, lat]",
            get_color="[150, 150, 150, 100]",
            get_radius=600,
            pickable=True,
        )
    ]
    
    st.pydeck_chart(pdk.Deck(
        layers=layers,
        initial_view_state=view_state,
        tooltip={"text": "{자치구}\n종합점수: {total_score:.2f}\nA통근: {time_a}분\nB통근: {time_b}분"}
    ))

with col_table:
    st.subheader("🏆 추천 랭킹 TOP 5")
    display_cols = ['자치구', 'time_a', 'time_b', 'total_commute', '평균매매가', '별점']
    st.dataframe(top5[display_cols].rename(columns={
        'time_a': 'A통근', 'time_b': 'B통근', 'total_commute': '합산통근', '평균매매가': '매매가(억)'
    }), use_container_width=True)
    
    st.info("""
    **분석 가이드**
    - 별점(★)은 가격, 통근, 인프라, 치안을 종합한 상대 점수입니다.
    - 맞벌이 부부의 경우 두 사람의 통근 시간을 동시에 만족하는 지역을 우선 추출합니다.
    """)

# --- 하단 섹션 ---
with st.expander("📝 상세 분석 데이터 (필터 반영 전체)"):
    st.write(df.sort_values('total_score', ascending=False))
