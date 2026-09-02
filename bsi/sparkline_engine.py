"""
bsi/sparkline_engine.py
Renders fenologische sparkline-grafieken met normalisatie (1.0) en rode 'vandaag' marker.
"""

import io
import base64
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from datetime import datetime
from typing import List, Dict, Any, Optional


class SparklineEngine:
    MONTH_TICKS = [1, 5, 9, 14, 18, 22, 26, 31, 35, 40, 44, 48]
    MONTH_LABELS = ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"]

    @classmethod
    def prepare_normalized_buffer(cls, week_rows: List[Dict[str, Any]]) -> np.ndarray:
        buffer = np.zeros(54, dtype=np.float32)
        for row in week_rows:
            week = int(row.get("week", -1))
            count = float(row.get("count", 0.0))
            if 0 <= week <= 53:
                buffer[week] = count

        max_val = np.max(buffer)
        if max_val > 0:
            buffer = buffer / max_val
        return buffer

    @classmethod
    def render_sparkline_png_bytes(
        cls,
        normalized_data: np.ndarray,
        target_dt: Optional[datetime] = None,
        width_px: int = 260,
        height_px: int = 65
    ) -> bytes:
        if target_dt is None:
            target_dt = datetime.now()

        current_week = target_dt.isocalendar().week
        current_week = max(0, min(53, current_week))

        dpi = 100
        fig_w = width_px / dpi
        fig_h = height_px / dpi

        fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=dpi)
        fig.patch.set_facecolor('#FFFFFF')
        ax.set_facecolor('#FFFFFF')

        x = np.arange(len(normalized_data))

        ax.plot(x, normalized_data, color='#4CAF50', linewidth=1.6, zorder=2)
        ax.fill_between(x, normalized_data, color='#4CAF50', alpha=0.2, zorder=1)

        ax.axvline(x=current_week, color='#FF5252', linestyle='--', linewidth=1.3, zorder=3)
        ax.scatter([current_week], [normalized_data[current_week]], color='#FF5252', s=14, zorder=4)

        ax.set_xticks(cls.MONTH_TICKS)
        ax.set_xticklabels(cls.MONTH_LABELS, color='#555555', fontsize=6)
        ax.tick_params(axis='x', colors='#555555', length=1, pad=1)

        ax.set_yticks([])
        ax.set_xlim(0, 53)
        ax.set_ylim(-0.05, 1.1)

        for spine in ['top', 'right', 'left', 'bottom']:
            ax.spines[spine].set_visible(False)

        plt.tight_layout(pad=0.1)

        buf = io.BytesIO()
        plt.savefig(buf, format='png', facecolor=fig.get_facecolor(), edgecolor='none')
        plt.close(fig)
        buf.seek(0)
        return buf.getvalue()

    @classmethod
    def get_sparkline_base64(cls, normalized_data: np.ndarray, target_dt: Optional[datetime] = None, width_px: int = 260, height_px: int = 65) -> str:
        png_bytes = cls.render_sparkline_png_bytes(normalized_data, target_dt, width_px=width_px, height_px=height_px)
        b64_str = base64.b64encode(png_bytes).decode('utf-8')
        return f"data:image/png;base64,{b64_str}"