"""
Trail Pacemaker - Streamlit 웹앱
실행:
  streamlit run streamlit_app.py

핸드폰에서 사용:
  1) PC에서 실행 후, 같은 Wi-Fi의 폰 브라우저로 http://<PC-IP>:8501 접속
  2) 또는 Streamlit Community Cloud / Hugging Face Spaces 에 배포
  3) 폰 브라우저의 '홈 화면에 추가'로 PWA처럼 사용
"""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

# analyzer.py 위치 (trail_app 폴더) 를 import 경로에 추가
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE / "trail_app"))

from analyzer import (  # noqa: E402
    CP,
    analyze,
    format_segment,
    parse_gpx,
    render_elevation_chart_png,
)

# ---------- 페이지 설정 ----------
st.set_page_config(
    page_title="Trail Pacemaker",
    page_icon="🏔️",
    layout="centered",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
      .block-container {padding-top: 1.2rem; padding-bottom: 2rem; max-width: 720px;}
      .stButton>button {width: 100%;}
      .cp-row {padding: 4px 8px; border-radius: 6px; background:#F5F7FA; margin-bottom:4px;}
      .credit {color:#e67e22; font-weight:600;}
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------- 헤더 ----------
c1, c2 = st.columns([3, 1])
with c1:
    st.title("🏔️ Trail Pacemaker")
with c2:
    st.markdown("<div class='credit'>Made By Hmi</div>", unsafe_allow_html=True)
st.caption("GPX 파일을 업로드하고 체크포인트를 관리해 프로급 페이싱 전략을 받아보세요.")

# ---------- 세션 상태 ----------
if "cps" not in st.session_state:
    st.session_state.cps = [CP("Start", 0.0, 0.0)]
if "selected_idx" not in st.session_state:
    st.session_state.selected_idx = 0


def _reset_form_fields():
    for k in ("f_name", "f_km", "f_cutoff"):
        st.session_state.pop(k, None)


# ---------- 1. 러너 정보 ----------
with st.container(border=True):
    st.subheader("1. 러너 신체 정보")
    col_h, col_w = st.columns(2)
    height = col_h.number_input("키 (cm)", min_value=100.0, max_value=230.0, value=178.0, step=1.0)
    weight = col_w.number_input("몸무게 (kg)", min_value=30.0, max_value=200.0, value=85.0, step=1.0)

# ---------- 2. 목표 시간 ----------
with st.container(border=True):
    st.subheader("2. 목표 완주 시간")
    target = st.number_input(
        "목표 시간 (h) — 예: 5시간 30분 → 5.5",
        min_value=0.5,
        max_value=48.0,
        value=5.5,
        step=0.1,
    )

# ---------- 3. CP 관리 ----------
with st.container(border=True):
    st.subheader("3. 체크포인트 (CP) 관리")

    cps: list[CP] = st.session_state.cps
    labels = [
        f"{i}. {cp.name}  ({cp.km} km)" + (f"  · 컷오프 {cp.cutoff}h" if cp.cutoff > 0 else "")
        for i, cp in enumerate(cps)
    ]
    sel = st.radio(
        "리스트 (선택 후 아래 폼에서 수정/삭제)",
        options=list(range(len(cps))),
        format_func=lambda i: labels[i],
        index=min(st.session_state.selected_idx, len(cps) - 1),
        key="cp_radio",
    )
    st.session_state.selected_idx = sel
    picked = cps[sel]

    with st.form("cp_form", clear_on_submit=False):
        col_a, col_b, col_c = st.columns([2, 1, 1])
        name = col_a.text_input("CP 이름", value=picked.name, key="f_name")
        km = col_b.number_input(
            "누적 km", min_value=0.0, max_value=1000.0, value=float(picked.km), step=0.1, key="f_km"
        )
        cutoff = col_c.number_input(
            "컷오프(h)", min_value=0.0, max_value=100.0, value=float(picked.cutoff), step=0.1, key="f_cutoff"
        )
        b1, b2, b3, b4 = st.columns(4)
        add_btn = b1.form_submit_button("➕ 추가", use_container_width=True)
        mod_btn = b2.form_submit_button("✏️ 수정", use_container_width=True)
        del_btn = b3.form_submit_button("🗑️ 삭제", use_container_width=True)
        rst_btn = b4.form_submit_button("♻️ 초기화", use_container_width=True)

    if add_btn:
        if not name.strip():
            st.warning("CP 이름을 입력하세요.")
        else:
            cps.append(CP(name.strip(), float(km), float(cutoff)))
            cps.sort(key=lambda c: c.km)
            st.session_state.selected_idx = next(
                (i for i, c in enumerate(cps) if c.name == name and c.km == km), 0
            )
            st.rerun()

    if mod_btn:
        if picked.name == "Start" and picked.km == 0.0:
            st.warning("출발점(Start)은 수정할 수 없습니다.")
        elif not name.strip():
            st.warning("CP 이름을 입력하세요.")
        else:
            cps[sel] = CP(name.strip(), float(km), float(cutoff))
            cps.sort(key=lambda c: c.km)
            st.rerun()

    if del_btn:
        if picked.name == "Start" and picked.km == 0.0:
            st.warning("출발점(Start)은 삭제할 수 없습니다.")
        else:
            del cps[sel]
            st.session_state.selected_idx = 0
            st.rerun()

    if rst_btn:
        st.session_state.cps = [CP("Start", 0.0, 0.0)]
        st.session_state.selected_idx = 0
        st.rerun()

# ---------- 4. GPX 업로드 ----------
with st.container(border=True):
    st.subheader("4. GPX 파일 업로드")
    # NOTE: iOS Safari(아이폰)는 .gpx 확장자에 대한 UTI가 없어 type=["gpx"]로
    #       필터링하면 파일 앱에서 GPX가 비활성화되어 선택이 불가능합니다.
    #       따라서 확장자 필터를 제거하고, 업로드 후 서버 측에서 확장자를 검증합니다.
    gpx_file = st.file_uploader(
        "코스 GPX 파일을 선택하세요 (.gpx)",
        type=None,
        accept_multiple_files=False,
    )
    if gpx_file is not None and not gpx_file.name.lower().endswith(".gpx"):
        st.error("GPX 파일(.gpx)만 업로드할 수 있습니다.")
        gpx_file = None

# ---------- 5. 분석 실행 ----------
run = st.button("🏃 전략 분석 시작", type="primary", use_container_width=True)

if run:
    if gpx_file is None:
        st.error("GPX 파일을 먼저 업로드하세요.")
        st.stop()
    if len(st.session_state.cps) < 2:
        st.error("도착점(Finish)을 포함해 최소 1개 이상의 CP를 추가하세요.")
        st.stop()

    try:
        with st.spinner("GPX 파싱 및 분석 중..."):
            df = parse_gpx(gpx_file.getvalue())
            result = analyze(df, st.session_state.cps, float(target), float(height), float(weight))

        st.success("분석 완료!")

        # 요약
        m1, m2, m3 = st.columns(3)
        m1.metric("총 거리", f"{result.total_dist:.1f} km")
        m2.metric("총 상승고도", f"{result.total_gain:.0f} m")
        m3.metric("목표 시간", f"{target} h")

        # 고도 프로파일 이미지
        png = render_elevation_chart_png(result, float(target))
        st.image(png, caption="고도 프로파일 & CP", use_container_width=True)

        # 구간별 결과
        st.subheader("📋 구간별 전략")
        for seg in result.segments:
            with st.expander(
                f"🏃 {seg.from_name} ➔ {seg.to_name}  ({seg.seg_dist:.1f} km)", expanded=True
            ):
                st.code(format_segment(seg), language=None)

        # 텍스트 다운로드
        full_text = "\n".join(result.header_lines) + "\n" + "=" * 55 + "\n\n"
        full_text += "\n\n".join(format_segment(s) for s in result.segments)
        st.download_button(
            "💾 결과 텍스트 저장 (.txt)",
            data=full_text.encode("utf-8"),
            file_name="pacing_strategy.txt",
            mime="text/plain",
            use_container_width=True,
        )

    except Exception as ex:
        st.exception(ex)

st.markdown(
    "<hr><div style='text-align:center; color:#999; font-size:12px;'>"
    "Trail Running Race Pacemaker | Made By Hmi"
    "</div>",
    unsafe_allow_html=True,
)
