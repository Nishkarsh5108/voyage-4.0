"""Shared helpers for EDA scripts: bounded DuckDB connection, chart style, markdown report writer.

Chart style follows one fixed system: a single categorical order (never cycled), thin marks,
recessive grid, text in ink colours only, a legend whenever there are two or more series.
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
INTERIM = ROOT / "data" / "interim"
REPORTS = ROOT / "reports" / "eda"

SURFACE, INK, INK2, MUTED, GRID, AXIS = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
# categorical slots, fixed order: blue, orange, aqua, yellow, magenta, green, violet, red
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
SEQ = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "font.family": ["Segoe UI", "DejaVu Sans", "sans-serif"], "font.size": 10,
    "text.color": INK, "axes.labelcolor": INK2, "axes.titlecolor": INK,
    "axes.titlesize": 12, "axes.titleweight": "semibold", "axes.titlelocation": "left", "axes.titlepad": 10,
    "axes.edgecolor": AXIS, "axes.linewidth": 1, "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 1, "axes.axisbelow": True,
    "xtick.color": MUTED, "ytick.color": MUTED, "xtick.labelcolor": INK2, "ytick.labelcolor": INK2,
    "xtick.major.size": 0, "ytick.major.size": 0,
    "lines.linewidth": 2, "lines.solid_capstyle": "round", "lines.solid_joinstyle": "round",
    "legend.frameon": False, "legend.fontsize": 9, "figure.dpi": 110, "savefig.dpi": 160, "savefig.bbox": "tight",
})


def connect(memory: str = "1500MB", threads: int = 3) -> duckdb.DuckDBPyConnection:
    """DuckDB connection that stays inside a small memory budget (the machine is shared)."""
    tmp = INTERIM / "duckdb_tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute(f"SET memory_limit='{memory}'; SET threads={threads}; SET temp_directory='{tmp.as_posix()}';")
    con.execute("SET preserve_insertion_order=false;")
    return con


def fmt_num(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        if abs(v) >= 1000:
            return f"{v:,.0f}"
        return f"{v:.3g}" if abs(v) < 1 else f"{v:,.2f}".rstrip("0").rstrip(".")
    if isinstance(v, int):
        return f"{v:,}"
    return str(v)


def barh(ax, labels, values, color=SERIES[0], value_fmt="{:,.0f}", xlabel=None, title=None):
    """Horizontal bars for one series, value at the tip, no legend (the title names the series)."""
    labels, values = list(labels)[::-1], list(values)[::-1]
    ax.barh(labels, values, height=0.62, color=color, linewidth=0)
    ax.grid(axis="y", visible=False)
    top = max(values) if values else 1
    for i, v in enumerate(values):
        ax.text(v + top * 0.012, i, value_fmt.format(v), va="center", ha="left", color=INK2, fontsize=9)
    ax.set_xlim(0, top * 1.14)
    if xlabel:
        ax.set_xlabel(xlabel)
    if title:
        ax.set_title(title)


def fig_for_bars(n: int, width: float = 7.5):
    """Figure sized so each bar stays thin (roughly 20 px) however many rows there are."""
    return plt.subplots(figsize=(width, max(1.6, 0.3 * n + 1.0)))


class Report:
    """Collects markdown + figures + a machine-readable stats dict, then writes them under reports/eda/."""

    def __init__(self, slug: str, title: str):
        self.slug, self.lines, self.stats = slug, [f"# {title}", ""], {}
        self.figdir = REPORTS / "figures" / slug
        self.figdir.mkdir(parents=True, exist_ok=True)

    def h(self, text: str, level: int = 2):
        self.lines += [f"{'#' * level} {text}", ""]

    def p(self, text: str):
        self.lines += [text, ""]

    def bullets(self, items):
        self.lines += [f"- {i}" for i in items] + [""]

    def table(self, headers, rows, align=None):
        rows = [[fmt_num(c) if not isinstance(c, str) else c.replace("|", "\\|").replace("\n", " ") for c in r] for r in rows]
        align = align or ["---"] + ["---:"] * (len(headers) - 1)
        self.lines.append("| " + " | ".join(headers) + " |")
        self.lines.append("|" + "|".join(align) + "|")
        self.lines += ["| " + " | ".join(r) + " |" for r in rows] + [""]

    def fig(self, fig, name: str, caption: str):
        path = self.figdir / f"{name}.png"
        fig.savefig(path)
        plt.close(fig)
        self.lines += [f"![{caption}](figures/{self.slug}/{name}.png)", "", f"*{caption}*", ""]

    def stat(self, key: str, value):
        self.stats[key] = value

    def write(self):
        REPORTS.mkdir(parents=True, exist_ok=True)
        (REPORTS / f"{self.slug}.md").write_text("\n".join(self.lines), encoding="utf-8")
        (REPORTS / f"{self.slug}.json").write_text(json.dumps(self.stats, indent=1, default=str), encoding="utf-8")
        print(f"wrote reports/eda/{self.slug}.md ({len(self.lines)} lines, {len(self.stats)} stats)")
