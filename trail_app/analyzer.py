"""
Trail Pacemaker - 순수 분석 로직 (UI 프레임워크 독립)
데스크톱/모바일/웹 어디서든 재사용 가능.
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from typing import List, Optional

import gpxpy
import pandas as pd
from haversine import haversine


@dataclass
class CP:
    name: str
    km: float
    cutoff: float = 0.0  # 누적 컷오프(시간). 0이면 없음


@dataclass
class SegmentResult:
    from_name: str
    to_name: str
    seg_dist: float
    seg_gain: float
    seg_loss: float
    seg_max_up: float
    seg_max_down: float
    seg_target_mins: float
    cumulative_target_mins: float
    strategy_lines: List[str]
    cum_km_at_end: float


@dataclass
class AnalysisResult:
    total_dist: float
    total_gain: float
    base_pace: float  # 분/유효거리km
    segments: List[SegmentResult]
    df: pd.DataFrame  # 시각화용
    header_lines: List[str]


def parse_gpx(source) -> pd.DataFrame:
    """source: 파일 경로(str) 또는 파일-라이크 객체 또는 bytes."""
    if isinstance(source, (bytes, bytearray)):
        gpx = gpxpy.parse(io.BytesIO(source).read().decode("utf-8", errors="ignore"))
    elif isinstance(source, str):
        with open(source, "r", encoding="utf-8") as f:
            gpx = gpxpy.parse(f)
    else:
        gpx = gpxpy.parse(source)

    data = []
    for track in gpx.tracks:
        for segment in track.segments:
            for p in segment.points:
                data.append(
                    {
                        "latitude": p.latitude,
                        "longitude": p.longitude,
                        "elevation": p.elevation if p.elevation is not None else 0.0,
                    }
                )
    if not data:
        raise ValueError("GPX 파일에 트랙 포인트가 없습니다.")
    return pd.DataFrame(data)


def enrich_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """거리/고도/경사도/누적거리 컬럼을 추가."""
    n = len(df)
    dist = [0.0] * n
    ele_diff = [0.0] * n
    grad = [0.0] * n
    lats = df["latitude"].to_numpy()
    lons = df["longitude"].to_numpy()
    eles = df["elevation"].to_numpy()

    for i in range(1, n):
        d = haversine((lats[i - 1], lons[i - 1]), (lats[i], lons[i]))
        dist[i] = d
        ed = float(eles[i] - eles[i - 1])
        ele_diff[i] = ed
        if d > 0:
            grad[i] = (ed / (d * 1000.0)) * 100.0

    df = df.copy()
    df["distance_km"] = dist
    df["ele_diff"] = ele_diff
    df["gradient"] = grad
    # GPS 노이즈 필터
    df["gradient"] = df["gradient"].clip(lower=-45, upper=45)
    df["gradient"] = df["gradient"].rolling(window=5, min_periods=1).mean()
    df["cumulative_distance"] = df["distance_km"].cumsum()
    df["gain"] = df["ele_diff"].apply(lambda x: x if x > 0 else 0.0)
    df["loss"] = df["ele_diff"].apply(lambda x: abs(x) if x < 0 else 0.0)
    return df


def _phase_advice(progress_ratio: float) -> tuple[str, str]:
    if progress_ratio <= 0.35:
        return (
            "🟢 초반부",
            "체력이 넘치더라도 오버페이스를 절대 주의하세요. 평지에서도 에너지를 비축하며 천천히 운용해야 합니다.",
        )
    if progress_ratio <= 0.70:
        return (
            "🟡 중반부",
            "다리가 무거워지기 시작합니다. 일정한 케이던스를 유지하고 보급(수분/탄수화물) 타이밍을 놓치지 마세요.",
        )
    return (
        "🔴 후반부",
        "근육 경련(쥐) 발생 위험이 큽니다. 보폭을 평소의 절반으로 줄이고 상체를 적극 활용해 하체를 아끼세요.",
    )


def _terrain_advice(seg_gain: float, seg_loss: float) -> str:
    if seg_gain > 300 and seg_loss < seg_gain * 0.2:
        return "고도를 한 번에 치고 올라가는 '지속형 업힐'입니다. 리듬이 깨지지 않게 일정한 케이던스를 유지하세요."
    if seg_gain > 150 and seg_loss > 150:
        return "짧은 업다운이 반복되는 '펀치형 낙타등' 지형입니다. 인터벌처럼 체력이 깎이니 내리막에서 달리지 마세요."
    if seg_gain > seg_loss:
        return "전반적으로 완만하게 고도를 높여가는 구간입니다."
    if seg_loss > seg_gain:
        return "다운힐 위주로 구성되어 있어 시간 단축에 유리한 구간입니다."
    return "고도 변화가 적어 안정적인 페이스를 유지할 수 있는 평탄한 구간입니다."


def analyze(
    df: pd.DataFrame,
    cps: List[CP],
    target_time_hours: float,
    user_height: Optional[float] = None,
    user_weight: Optional[float] = None,
) -> AnalysisResult:
    df = enrich_dataframe(df)
    total_dist = float(df["cumulative_distance"].iloc[-1])
    total_gain = float(df["gain"].sum())

    effort_distance = total_dist + (total_gain / 100.0)
    base_pace = (target_time_hours * 60.0) / effort_distance

    header = [
        f"🏃 러너 정보: 키 {user_height}cm / 몸무게 {user_weight}kg"
        if user_height and user_weight
        else "🏃 러너 정보: -",
        f"🏁 대회 최종 목표 시간: {target_time_hours}시간",
        f"총 실제 거리: {total_dist:.1f} km / 총 상승 고도: {total_gain:.0f} m",
    ]

    # cps는 이미 km 오름차순 가정. 아니면 정렬.
    cps_sorted = sorted(cps, key=lambda c: c.km)

    segments: List[SegmentResult] = []
    start_idx = 0
    cum_target = 0.0

    for i in range(1, len(cps_sorted)):
        cp_prev = cps_sorted[i - 1]
        cp = cps_sorted[i]
        end_indices = df[df["cumulative_distance"] >= cp.km].index
        end_idx = int(end_indices[0]) if len(end_indices) > 0 else len(df) - 1
        seg = df.iloc[start_idx:end_idx]
        if len(seg) == 0:
            continue

        seg_dist = float(seg["distance_km"].sum())
        seg_gain = float(seg["gain"].sum())
        seg_loss = float(seg["loss"].sum())
        seg_max_up = float(seg["gradient"].max())
        seg_max_down = float(seg["gradient"].min())

        seg_effort = seg_dist + (seg_gain / 100.0)
        seg_target = seg_effort * base_pace
        cum_target += seg_target

        strategy: List[str] = []
        phase, fatigue = _phase_advice(cp.km / total_dist if total_dist else 0.0)
        strategy.append(f"[{phase}] {fatigue}")
        strategy.append(f"[지형 형태] {_terrain_advice(seg_gain, seg_loss)}")

        if cp.cutoff > 0:
            cutoff_mins = cp.cutoff * 60.0
            buf = cutoff_mins - cum_target
            if buf >= 0:
                strategy.append(
                    f"[대회 운영] 현재 페이스 유지 시 컷오프 대비 약 '{int(buf)}분' 여유 예상. 휴식을 챙기세요."
                )
            else:
                strategy.append(
                    f"[대회 운영] 🚨 컷오프 위험! 현재 페이스보다 '{int(abs(buf))}분' 지연됩니다. 다운힐에서 속도를 높이세요."
                )

        segments.append(
            SegmentResult(
                from_name=cp_prev.name,
                to_name=cp.name,
                seg_dist=seg_dist,
                seg_gain=seg_gain,
                seg_loss=seg_loss,
                seg_max_up=seg_max_up,
                seg_max_down=seg_max_down,
                seg_target_mins=seg_target,
                cumulative_target_mins=cum_target,
                strategy_lines=strategy,
                cum_km_at_end=float(df.loc[end_idx, "cumulative_distance"]),
            )
        )
        start_idx = end_idx

    return AnalysisResult(
        total_dist=total_dist,
        total_gain=total_gain,
        base_pace=base_pace,
        segments=segments,
        df=df,
        header_lines=header,
    )


def format_segment(seg: SegmentResult) -> str:
    h = int(seg.seg_target_mins // 60)
    m = int(seg.seg_target_mins % 60)
    cum_h = int(seg.cumulative_target_mins // 60)
    cum_m = int(seg.cumulative_target_mins % 60)
    lines = [
        f"🏃 {seg.from_name} ➔ {seg.to_name}",
        f" - 거리/고도 : {seg.seg_dist:.1f} km / 상승 {seg.seg_gain:.0f}m, 하강 {seg.seg_loss:.0f}m",
        f" - 지형 요약 : 최고 오르막 {seg.seg_max_up:.1f}% / 최고 내리막 {seg.seg_max_down:.1f}%",
        f" - 목표 시간 : {h}시간 {m}분 (누적: {cum_h}시간 {cum_m}분)",
    ]
    for idx, s in enumerate(seg.strategy_lines):
        if idx == 0:
            lines.append(f" - 💡 전략   : {s}")
        else:
            lines.append(f"               {s}")
    return "\n".join(lines)


def render_elevation_chart_png(result: AnalysisResult, target_time_hours: float) -> bytes:
    """matplotlib으로 고도 프로파일 PNG를 만들어 bytes로 반환."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    df = result.df
    fig, ax = plt.subplots(figsize=(10, 5), dpi=140)
    ax.plot(df["cumulative_distance"], df["elevation"], color="black", alpha=0.85, linewidth=1.2)
    ax.fill_between(df["cumulative_distance"], df["elevation"], color="skyblue", alpha=0.35)

    colors = ["red", "blue", "green", "orange", "purple", "brown"]
    ymax = float(df["elevation"].max())
    for i, seg in enumerate(result.segments):
        c = colors[i % len(colors)]
        ax.axvline(x=seg.cum_km_at_end, color=c, linestyle="--", alpha=0.7, linewidth=1)
        ax.text(
            seg.cum_km_at_end,
            ymax * 0.9,
            f" {seg.to_name}\n {seg.cum_km_at_end:.1f}km",
            color=c,
            fontweight="bold",
            fontsize=8,
        )

    ax.set_title(f"Race Pacing Strategy (Target: {target_time_hours} H)")
    ax.set_xlabel("Distance (km)")
    ax.set_ylabel("Elevation (m)")
    ax.grid(True, linestyle=":", alpha=0.6)
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()
