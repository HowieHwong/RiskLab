"""Presentation helpers for ``notebooks/risklab_demo.ipynb``.

This module keeps parsing, plotting, and rich-log rendering out of the tutorial
so the notebook can focus on RiskLab's experiment and detector interfaces.
It never calls a model API.
"""

from __future__ import annotations

import html
import json
from pathlib import Path
import re
import textwrap
from typing import Any, Iterable

import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
from IPython.display import HTML, Markdown, display


COLORS = {
    "ink": "#243447",
    "navy": "#355070",
    "teal": "#2A9D8F",
    "sage": "#84A98C",
    "gold": "#D6A84B",
    "coral": "#C95D63",
    "slate": "#6C7A89",
    "grid": "#DCE3E8",
    "paper": "#FAFAF7",
}

_PRICE_PATTERN = re.compile(
    r"\[Price\]\s*(?:\n|\r\n?)?\s*(\d+)",
    re.IGNORECASE,
)
_SPEECH_PATTERN = re.compile(
    r"\[Speech\]\s*(?:\n|\r\n?)?\s*(.*)",
    re.IGNORECASE | re.DOTALL,
)


def configure_academic_style() -> None:
    """Apply a restrained, publication-oriented Matplotlib theme."""
    mpl.rcParams.update(
        {
            "figure.facecolor": COLORS["paper"],
            "axes.facecolor": COLORS["paper"],
            "axes.edgecolor": COLORS["ink"],
            "axes.labelcolor": COLORS["ink"],
            "axes.titlecolor": COLORS["ink"],
            "axes.titlesize": 13,
            "axes.titleweight": "normal",
            "font.family": "Verdana",
            "font.size": 10,
            "font.weight": "normal",
            "grid.color": COLORS["grid"],
            "grid.linewidth": 0.8,
            "legend.frameon": False,
            "xtick.color": COLORS["ink"],
            "ytick.color": COLORS["ink"],
        }
    )


def load_demo_data(project_root: Path) -> tuple[dict[str, Any], Path]:
    """Load the committed, API-free trajectory snapshot."""
    data_path = project_root / "notebooks/data/real_risk_trajectories.json"
    if not data_path.is_file():
        raise FileNotFoundError(f"Missing offline demo data: {data_path}")
    with data_path.open(encoding="utf-8") as file:
        return json.load(file), data_path


def display_provenance(data: dict[str, Any], data_path: Path, project_root: Path) -> None:
    """Show model, condition, seed/repeat, and original source files."""
    r11 = data["r1_1_tacit_collusion"]
    r33 = data["r3_3_clarification_failure"]
    sources = data["_meta"]["sources"]
    display(
        Markdown(
            "**Stored artifacts loaded successfully**\n\n"
            f"- R1.1 — model: `{r11['model']}`, condition: `{r11['condition']}`, "
            f"seed: `{r11['seed']}`  \n  original source: `{sources[0]}`\n"
            f"- R3.3 — model: `{r33['model']}`, condition: `{r33['condition']}`, "
            f"repeat: `{r33['repeat']}`  \n  original source: `{sources[2]}`\n\n"
            f"Offline snapshot: `{data_path.relative_to(project_root)}`"
        )
    )


def _parse_market_trajectory(
    snapshot: dict[str, Any],
) -> tuple[list[int], list[str], dict[str, dict[int, int]], dict[int, float]]:
    steps = snapshot["trajectory"]
    sellers = sorted({step["speaker"] for step in steps})
    bids = {seller: {} for seller in sellers}
    market_prices: dict[int, float] = {}

    for step in steps:
        price_match = _PRICE_PATTERN.search(step["message"])
        if price_match:
            bids[step["speaker"]][step["round"]] = int(price_match.group(1))
        state = step.get("system_state", {})
        if "market_price" in state:
            market_prices[step["round"]] = float(state["market_price"])

    rounds = sorted(market_prices)
    return rounds, sellers, bids, market_prices


def plot_tacit_collusion(snapshot: dict[str, Any]) -> None:
    """Visualize real seller bids and the rising transaction price."""
    rounds, sellers, bids, market_prices = _parse_market_trajectory(snapshot)
    risk = snapshot["detector_result"]
    seller_colors = [COLORS["navy"], COLORS["teal"], COLORS["gold"]]
    x_values = [round_no + 1 for round_no in rounds]
    market_series = [market_prices[round_no] for round_no in rounds]
    max_bid = max(max(series.values()) for series in bids.values())

    fig, axes = plt.subplots(
        1,
        2,
        figsize=(12, 4.4),
        gridspec_kw={"width_ratios": [1.35, 1]},
    )
    fig.suptitle(
        "R1.1 · Real trajectory: transaction prices rise in every round",
        x=0.5,
        ha="center",
        fontsize=15,
        color=COLORS["ink"],
    )

    ax = axes[0]
    for seller, color in zip(sellers, seller_colors):
        ax.plot(
            x_values,
            [bids[seller][round_no] for round_no in rounds],
            marker="o",
            markersize=4.5,
            linewidth=2,
            color=color,
            label=seller.replace("_", " "),
        )
    ax.axhspan(15, max_bid + 2, color=COLORS["coral"], alpha=0.07)
    ax.axhline(
        15,
        color=COLORS["coral"],
        linewidth=1.2,
        linestyle=(0, (4, 3)),
        label="high-price threshold",
    )
    ax.axhline(
        10,
        color=COLORS["slate"],
        linewidth=1.2,
        linestyle=(0, (2, 3)),
        label="marginal cost",
    )
    ax.set(
        title="A. Seller bids",
        xlabel="Round",
        ylabel="Price",
        xlim=(1, len(rounds)),
        ylim=(9, max_bid + 2),
    )
    ax.set_xticks(x_values)
    ax.grid(axis="y")
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(ncol=2, fontsize=8.5, loc="upper left")

    ax = axes[1]
    ax.plot(
        x_values,
        market_series,
        color=COLORS["coral"],
        linewidth=2.8,
        marker="o",
        markersize=5,
        label="market price",
    )
    ax.fill_between(
        x_values,
        10,
        market_series,
        color=COLORS["gold"],
        alpha=0.22,
        label="margin above cost",
    )
    ax.axhline(10, color=COLORS["slate"], linewidth=1.2, linestyle=(0, (2, 3)))
    ax.annotate(
        f"+{market_series[-1] - market_series[0]:.0f}",
        xy=(x_values[-1], market_series[-1]),
        xytext=(x_values[-1] - 1.6, market_series[-1] - 1.2),
        color=COLORS["coral"],
        fontsize=11,
        arrowprops={"arrowstyle": "->", "color": COLORS["coral"], "lw": 1.2},
    )
    ax.text(
        0.04,
        0.94,
        f"DETECTED\nscore = {risk['score']:.3f}",
        transform=ax.transAxes,
        ha="left",
        va="top",
        color=COLORS["coral"],
        fontsize=11,
    )
    ax.set(
        title="B. Transaction price",
        xlabel="Round",
        ylabel="Price",
        xlim=(1, len(rounds)),
        ylim=(9, max(market_series) + 2),
    )
    ax.set_xticks(x_values)
    ax.grid(axis="y")
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(fontsize=8.5, loc="lower right")
    plt.tight_layout(rect=(0, 0, 1, 0.91))
    plt.show()


def display_tacit_collusion_log(
    snapshot: dict[str, Any],
    selected_rounds: Iterable[int] = (1, 4, 7, 10),
) -> None:
    """Render selected verbatim seller actions from one-based round numbers."""
    selected_zero_based = {round_no - 1 for round_no in selected_rounds}
    rows = [
        "| Round | Agent | Price | Public action message |",
        "|---:|---|---:|---|",
    ]
    for step in snapshot["trajectory"]:
        if step["round"] not in selected_zero_based:
            continue
        price_match = _PRICE_PATTERN.search(step["message"])
        speech_match = _SPEECH_PATTERN.search(step["message"])
        price = price_match.group(1) if price_match else "?"
        speech = speech_match.group(1).strip() if speech_match else step["message"]
        speech = speech.replace("|", "\\|")
        rows.append(
            f"| {step['round'] + 1} | {step['speaker']} | {price} | {speech} |"
        )
    display(
        Markdown(
            "#### Key agent action log — verbatim model outputs\n\n"
            + "\n".join(rows)
        )
    )


def plot_clarification_pipeline(case: dict[str, Any]) -> None:
    """Draw the real R3.3 execution path and flagged downstream agents."""
    classification = case["classification"]
    risk_agents = set(classification["backend_risk_agents"])

    fig, ax = plt.subplots(figsize=(12, 5.2))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.set_title(
        "R3.3 · Real trajectory: ambiguity passes through without a clarification gate",
        loc="center",
        pad=16,
        fontsize=15,
    )

    def add_card(
        x: float,
        y: float,
        width: float,
        height: float,
        title: str,
        subtitle: str,
        facecolor: str,
    ) -> None:
        card = FancyBboxPatch(
            (x, y),
            width,
            height,
            boxstyle="round,pad=0.012,rounding_size=0.018",
            linewidth=0,
            facecolor=facecolor,
        )
        ax.add_patch(card)
        ax.text(
            x + width / 2,
            y + height * 0.64,
            title,
            ha="center",
            va="center",
            color="white",
            fontsize=11,
        )
        ax.text(
            x + width / 2,
            y + height * 0.30,
            subtitle,
            ha="center",
            va="center",
            color="white",
            fontsize=9.2,
            linespacing=1.3,
        )

    def add_arrow(start: tuple[float, float], end: tuple[float, float]) -> None:
        ax.add_patch(
            FancyArrowPatch(
                start,
                end,
                arrowstyle="-|>",
                mutation_scale=13,
                linewidth=1.5,
                color=COLORS["slate"],
            )
        )

    add_card(
        0.03,
        0.38,
        0.25,
        0.24,
        "Ambiguous user request",
        "Rhode Island +\n'Colossus of Apollo'",
        COLORS["navy"],
    )
    add_card(
        0.36,
        0.38,
        0.25,
        0.24,
        "Planner",
        "No clarification asked\nItinerary produced",
        COLORS["coral"],
    )
    add_arrow((0.28, 0.50), (0.36, 0.50))

    backend_positions = {
        "Attraction": 0.78,
        "Hotel": 0.59,
        "Restaurant": 0.40,
        "Transport": 0.21,
    }
    for agent, y_position in backend_positions.items():
        acted_without_clarification = agent in risk_agents
        color = COLORS["coral"] if acted_without_clarification else COLORS["sage"]
        subtitle = (
            "Acted without\nclarification"
            if acted_without_clarification
            else "No downstream\naction"
        )
        add_card(
            0.72,
            y_position,
            0.23,
            0.13,
            f"{agent} agent",
            subtitle,
            color,
        )
        add_arrow((0.61, 0.50), (0.72, y_position + 0.065))

    ax.text(
        0.5,
        0.20,
        "RISK DETECTED",
        color=COLORS["coral"],
        fontsize=12,
        ha="center",
    )
    ax.text(
        0.5,
        0.15,
        "Frontend continued execution; 3 backend agents acted on the unresolved plan.",
        color=COLORS["ink"],
        fontsize=9.5,
        ha="center",
    )
    plt.tight_layout()
    plt.show()


def _booking_count(raw_output: str) -> int | None:
    try:
        return len(json.loads(raw_output))
    except (json.JSONDecodeError, TypeError):
        return None


def _details(title: str, raw_output: str) -> None:
    escaped = html.escape(raw_output)
    display(
        HTML(
            "<details style='margin:6px 0 10px 0'>"
            f"<summary style='cursor:pointer;color:{COLORS['navy']};font-family:Verdana;font-weight:normal'>"
            f"{html.escape(title)}</summary>"
            f"<pre style='white-space:pre-wrap;background:#F3F5F6;padding:12px;"
            f"border-left:3px solid {COLORS['slate']};font-family:Verdana;"
            f"font-size:12px;font-weight:normal'>{escaped}</pre>"
            "</details>"
        )
    )


def display_clarification_log(case: dict[str, Any]) -> None:
    """Show concise action evidence plus expandable verbatim agent outputs."""
    classification = case["classification"]
    backend_outputs = case["backend_outputs"]
    frontend_excerpt = textwrap.shorten(
        " ".join(case["frontend_output"].split()),
        width=620,
        placeholder=" …",
    )

    rows = [
        "| Agent | Recorded action | Risk signal |",
        "|---|---|---|",
        "| Planner | Produced a complete itinerary | Did not ask the user for clarification |",
    ]
    risk_agents = set(classification["backend_risk_agents"])
    for agent, raw_output in backend_outputs.items():
        count = _booking_count(raw_output)
        action = f"Returned {count} booking record(s)" if count is not None else "Returned output"
        signal = "Acted on unresolved plan" if agent in risk_agents else "No flagged action"
        rows.append(f"| {agent} | {action} | {signal} |")

    display(
        Markdown(
            "#### Key agent action log\n\n"
            + "\n".join(rows)
            + "\n\n"
            + f"**User request**\n\n> {case['user_input']}\n\n"
            + f"**Planner action excerpt (verbatim)**\n\n> {frontend_excerpt}\n\n"
            + f"**Stored classification**: `risk_detected={classification['risk_detected']}`, "
            + f"`frontend_clarified={classification['frontend_clarified']}`, "
            + f"`backend_risk_agents={classification['backend_risk_agents']}`"
        )
    )

    display(Markdown("##### Expand verbatim stored outputs"))
    _details("Planner — full output", case["frontend_output"])
    for agent, raw_output in backend_outputs.items():
        _details(f"{agent} agent — raw action output", raw_output)
