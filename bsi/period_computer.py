"""
bsi/period_computer.py
Provides periodize_hours(...) used by forecast_system to group consecutive
hourly samples into contiguous periods where wind direction (rounded to the
16-label windrose) AND Beaufort are identical. Hours before sunrise and after
sunset are excluded by passing start_hour/end_hour.

The returned period objects contain representative statistics used by the
rest of the code (modal label, circular mean deg, median wind speed/bft,
avg temp/cloud/precip, start/end times and hours).
"""
from typing import List, Dict, Any
import math
import statistics

from .weather_service import WeatherManagerUtils


def _circular_mean_deg(deg_list: List[float]) -> float:
    if not deg_list:
        return 0.0
    x = sum(math.cos(math.radians(d)) for d in deg_list)
    y = sum(math.sin(math.radians(d)) for d in deg_list)
    mean_deg = (math.degrees(math.atan2(y, x)) + 360.0) % 360.0
    return mean_deg


def periodize_hours(
    hourly_samples: List[Dict[str, Any]],
    dir_tol_deg: float = 5.25,
    bft_tol: int = 0,
    precip_threshold: float = 80.0,
    max_gap_hours: int = 0,
    start_hour: int = 0,
    end_hour: int = 24,
) -> List[Dict[str, Any]]:
    """
    Group consecutive hourly samples into periods where wind_label (16-label)
    AND Beaufort (integer) are identical. Hours outside [start_hour, end_hour)
    are excluded.

    Parameters mirror how forecast_system calls this function so minimal changes
    are required there.
    """
    if not hourly_samples:
        return []

    # Normalize and parse samples, keep only those in the requested hour window
    parsed = []
    for s in sorted(hourly_samples, key=lambda x: x.get("time", "")):
        t = str(s.get("time", ""))
        try:
            tpart = t.split("T")[1]
            hour = int(tpart[:2])
            minute = int(tpart[3:5]) if len(tpart) >= 5 else 0
        except Exception:
            # If time parsing fails, skip sample
            continue

        if hour < int(start_hour) or hour >= int(end_hour):
            continue

        wind_deg = s.get("wind_deg")
        wind_speed = s.get("wind_speed")
        wind_deg = float(wind_deg) if wind_deg is not None else 0.0
        wind_speed = float(wind_speed) if wind_speed is not None else 0.0
        bft = WeatherManagerUtils.ms_to_beaufort(wind_speed)
        bft_int = int(round(bft))
        wind_label = WeatherManagerUtils.deg_to_16_wind_label(wind_deg)

        parsed.append({
            "time": t,
            "hour": hour,
            "minute": minute,
            "wind_deg": wind_deg,
            "wind_speed": wind_speed,
            "wind_bft": bft_int,
            "wind_label": WeatherManagerUtils.normalize_wind_label(wind_label),
            "temp": s.get("temp"),
            "cloud_cover": s.get("cloud_cover"),
            "precip_mm": s.get("precip_mm") if s.get("precip_mm") is not None else 0.0,
            "precip_prob": s.get("precip_prob") if s.get("precip_prob") is not None else 0.0,
        })

    if not parsed:
        return []

    periods: List[Dict[str, Any]] = []

    # infer the typical sampling interval (in hours) from the parsed samples
    hours_list = [p["hour"] for p in parsed]
    unique_hours = sorted(list(dict.fromkeys(hours_list)))
    diffs = [j - i for i, j in zip(unique_hours[:-1], unique_hours[1:]) if (j - i) > 0]
    if diffs:
        try:
            sample_interval = int(round(statistics.median(diffs)))
        except Exception:
            sample_interval = max(1, min(diffs))
    else:
        sample_interval = 1

    # adjacency threshold: allow merging when gap <= sample_interval + max_gap_hours
    adjacency_threshold = max(1, sample_interval + int(max_gap_hours))

    current = [parsed[0]]

    for nxt in parsed[1:]:
        cur = current[-1]
        # Decision: exact match on normalized 16-label AND exact integer Beaufort
        same_label = nxt["wind_label"] == cur["wind_label"]
        same_bft = nxt["wind_bft"] == cur["wind_bft"]
        # Measure gap in sample units (hours)
        hour_gap = nxt["hour"] - cur["hour"]
        if hour_gap < 0:
            hour_gap = adjacency_threshold

        if same_label and same_bft and hour_gap <= adjacency_threshold:
            # contiguous (by sampling cadence) and identical label + Bft -> merge
            current.append(nxt)
        else:
            # finalize current group
            periods.append(_aggregate_run(current, start_hour, end_hour, sample_interval))
            current = [nxt]

    if current:
        periods.append(_aggregate_run(current, start_hour, end_hour, sample_interval))

    # Filter out empty or very short periods if needed (keep as-is for now)
    return periods


def _aggregate_run(run: List[Dict[str, Any]], start_hour: int, end_hour: int, sample_interval: int = 1) -> Dict[str, Any]:
    hours = [r["hour"] for r in run]
    wind_speeds = [r["wind_speed"] for r in run]
    wind_degs = [r["wind_deg"] for r in run]
    bfts = [r["wind_bft"] for r in run]
    temps = [r["temp"] for r in run if r.get("temp") is not None]
    clouds = [r["cloud_cover"] for r in run if r.get("cloud_cover") is not None]
    prec_mm = [r["precip_mm"] for r in run]
    prec_prob = [r["precip_prob"] for r in run]

    # modal wind label (all same by construction, but compute defensively)
    labels = [r.get("wind_label") for r in run]
    modal_label = max(set(labels), key=labels.count) if labels else "NO"

    # circular mean for wind degrees
    modal_deg = _circular_mean_deg(wind_degs)

    try:
        median_speed = float(statistics.median(wind_speeds)) if wind_speeds else 0.0
    except Exception:
        median_speed = float(sum(wind_speeds) / len(wind_speeds)) if wind_speeds else 0.0

    try:
        median_bft = int(round(statistics.median(bfts))) if bfts else 0
    except Exception:
        median_bft = int(round(sum(bfts) / len(bfts))) if bfts else 0

    avg_temp = float(sum(temps) / len(temps)) if temps else None
    avg_cloud = float(sum(clouds) / len(clouds)) if clouds else None
    avg_prec_mm = float(sum(prec_mm) / len(prec_mm)) if prec_mm else 0.0
    avg_prec_prob = float(sum(prec_prob) / len(prec_prob)) if prec_prob else 0.0

    start_hour = int(min(hours))
    last_hour = int(max(hours))
    end_hour = last_hour + int(sample_interval)
    # Clip end_hour to requested window
    if end_hour > end_hour:
        end_hour = end_hour

    start_time = run[0]["time"].split("T")[1][:5]
    # end_time as last hour + sample_interval
    end_time = f"{end_hour:02d}:00"

    return {
        "start_time": start_time,
        "end_time": end_time,
        "start_hour": start_hour,
        "end_hour": end_hour,
        "modal_wind_label": modal_label,
        "modal_wind_deg": modal_deg,
        "median_wind_speed": median_speed,
        "median_bft": median_bft,
        "avg_temp": avg_temp,
        "avg_cloud": avg_cloud,
        "avg_precip_mm": avg_prec_mm,
        "avg_precip_prob": avg_prec_prob,
        "samples": len(run),
    }
