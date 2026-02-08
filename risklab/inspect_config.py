#!/usr/bin/env python3
"""
Config Inspector — pretty-print the full structure of a MAS experiment.

Usage
-----
    python -m risklab.inspect_config  path/to/config.yaml

Or as a library::

    from risklab.inspect_config import inspect_config
    inspect_config("experiments/configs/example_tacit_collusion.yaml")

The output includes:
    • Experiment meta-data
    • Task summary (+ inputs for acyclic pipelines)
    • Communication topology (adjacency matrix, edges, degrees)
    • Information flow (stages, cyclic/acyclic, stop conditions, named flows)
    • Simulated speaker sequence (first round)
    • Protocol & environment info
    • Agents table
    • Risks & evaluation metrics
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]

from risklab.topology import (
    CommunicationTopology,
    InformationFlowConfig,
    build_topology_from_config,
    stage_agents,
    is_parallel,
    flatten_flow_order,
    FlowOrder,
)
from risklab.tasks import TaskConfig


# ======================================================================
# Pretty-printing helpers
# ======================================================================

_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_CYAN = "\033[36m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_RED = "\033[31m"
_MAGENTA = "\033[35m"
_BLUE = "\033[34m"


def _h1(title: str) -> str:
    return f"\n{_BOLD}{_CYAN}{'═' * 60}{_RESET}\n{_BOLD}{_CYAN}  {title}{_RESET}\n{_BOLD}{_CYAN}{'═' * 60}{_RESET}"


def _h2(title: str) -> str:
    return f"\n{_BOLD}{_GREEN}── {title} ──{_RESET}"


def _kv(key: str, value: Any, indent: int = 2) -> str:
    pad = " " * indent
    return f"{pad}{_BOLD}{key}:{_RESET} {value}"


def _bullet(text: str, indent: int = 4) -> str:
    pad = " " * indent
    return f"{pad}{_DIM}•{_RESET} {text}"


def _warn(text: str) -> str:
    return f"  {_YELLOW}⚠  {text}{_RESET}"


def _ok(text: str) -> str:
    return f"  {_GREEN}✓  {text}{_RESET}"


def _err(text: str) -> str:
    return f"  {_RED}✗  {text}{_RESET}"


def _stage_repr(stage: Any) -> str:
    """Pretty-print a single flow stage."""
    if isinstance(stage, list):
        agents_str = ", ".join(stage)
        return f"{_MAGENTA}[{agents_str}]{_RESET} {_DIM}(parallel, {len(stage)} agents){_RESET}"
    return f"{_BLUE}{stage}{_RESET}"


# ======================================================================
# Adjacency matrix pretty-print
# ======================================================================

def _print_matrix(agents: List[str], matrix: List[List[int]]) -> None:
    """Print a nicely aligned adjacency matrix with row/col labels."""
    max_len = max(len(a) for a in agents)
    header_pad = " " * (max_len + 4)

    # Column headers
    col_labels = "  ".join(f"{a[:5]:>5}" for a in agents)
    print(f"{header_pad}{_DIM}{col_labels}{_RESET}")

    for i, row in enumerate(matrix):
        label = f"    {agents[i]:>{max_len}}"
        cells = []
        for j, val in enumerate(row):
            if val:
                cells.append(f"{_GREEN}{'1':>5}{_RESET}")
            else:
                cells.append(f"{_DIM}{'·':>5}{_RESET}")
        print(f"{label}  {'  '.join(cells)}")


# ======================================================================
# Flow visualization
# ======================================================================

def _flow_diagram(flow_order: FlowOrder) -> str:
    """Build a text-based flow diagram like: user → [A, B, C] → summary → user"""
    parts = []
    for stage in flow_order:
        if isinstance(stage, list):
            parts.append(f"[{', '.join(stage)}]")
        else:
            parts.append(stage)
    return f" {_DIM}→{_RESET} ".join(parts)


def _simulate_speakers(
    topo: CommunicationTopology,
    flow: InformationFlowConfig,
    protocol_type: str,
    protocol_params: Dict[str, Any],
    agent_ids: List[str],
    max_steps: int = 60,
    max_rounds_display: int = 3,
) -> List[Dict[str, Any]]:
    """Simulate the speaker sequence for display purposes.

    For cyclic flows shows up to *max_rounds_display* rounds.
    For acyclic flows shows exactly one pass through the pipeline.
    """
    from risklab.protocols.sequential import SequentialHandoff
    from risklab.protocols.broadcast import BroadcastDeliberation
    from risklab.protocols.market import MarketTurnBased
    from risklab.protocols.queue_based import QueueBasedExecution

    proto_map = {
        "sequential_handoff": SequentialHandoff,
        "broadcast_deliberation": BroadcastDeliberation,
        "market_turn_based": MarketTurnBased,
        "queue_based": QueueBasedExecution,
    }

    proto_cls = proto_map.get(protocol_type)
    if proto_cls is None:
        return []

    proto = proto_cls(agent_ids=agent_ids, topology=topo, flow=flow, **protocol_params)

    # For acyclic flows, show only 1 pass
    effective_max_rounds = 1 if not flow.cyclic else max_rounds_display

    steps = []
    for _ in range(max_steps):
        if proto.current_round >= effective_max_rounds:
            break

        speaker = proto.get_next_speaker()
        if speaker is None:
            break
        listeners = proto.get_listeners(speaker)
        steps.append({
            "round": proto.current_round,
            "speaker": speaker,
            "listeners": listeners,
            "stage": getattr(proto, "current_stage_index", None),
        })
        proto.advance()
        if proto.should_stop():
            break
    return steps


# ======================================================================
# Main inspection
# ======================================================================

def inspect_config(config_path_or_dict) -> None:
    """Parse and pretty-print a YAML experiment config.

    Parameters
    ----------
    config_path_or_dict : str | Path | dict
        Either a file path to a YAML config, or an already-parsed dict.
    """
    if isinstance(config_path_or_dict, dict):
        config = config_path_or_dict
    else:
        path = Path(config_path_or_dict)
        if not path.exists():
            print(_err(f"File not found: {config_path_or_dict}"))
            sys.exit(1)
        if yaml is None:
            print(_err("PyYAML is required.  Install with: pip install pyyaml"))
            sys.exit(1)
        with open(path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

    # ------------------------------------------------------------------
    # 1. Experiment
    # ------------------------------------------------------------------
    exp = config.get("experiment", {})
    print(_h1(f"Experiment: {exp.get('id', '(unnamed)')}"))
    if exp.get("description"):
        print(_kv("Description", exp["description"].strip()))

    # ------------------------------------------------------------------
    # 2. Task
    # ------------------------------------------------------------------
    task_cfg = config.get("task")
    if task_cfg:
        print(_h2("Task"))
        task = TaskConfig.from_dict(dict(task_cfg))
        print(_kv("task_id", task.task_id))
        print(_kv("task_type", task.task_type.value))
        if task.description:
            print(_kv("description", task.description.strip()))
        if task.success_criteria:
            print(_kv("success_criteria", task.success_criteria))
        if task.constraints:
            print(_kv("constraints", task.constraints))
        if task.expected_output:
            print(_kv("expected_output", task.expected_output))
        if task.inputs:
            print(_kv("inputs", f"{len(task.inputs)} inline item(s)"))
            for i, inp in enumerate(task.inputs):
                keys = list(inp.keys())
                preview = str(inp)[:80] + ("…" if len(str(inp)) > 80 else "")
                print(_bullet(f"[{i}] keys={keys}  {_DIM}{preview}{_RESET}"))
        if task.input_file:
            print(_kv("input_file", task.input_file))
            if task.input_key:
                print(_kv("input_key", task.input_key))
        if not task.inputs and not task.input_file:
            print(_kv("inputs", f"{_DIM}(none — pipeline runs once with empty input){_RESET}"))

    # ------------------------------------------------------------------
    # 2.5 LLM Configuration
    # ------------------------------------------------------------------
    # Support both inline llm: and external llm_config_path:
    llm_cfg = config.get("llm")
    llm_config_path = config.get("llm_config_path")
    
    # If external path is specified, try to load it
    if llm_config_path:
        print(_h2("LLM Configuration"))
        print(_kv("source", f"external file: {_CYAN}{llm_config_path}{_RESET}"))
        try:
            # Attempt to resolve relative to the config file's directory
            if isinstance(config_path_or_dict, str):
                import os
                base_dir = os.path.dirname(os.path.abspath(config_path_or_dict))
                full_path = os.path.join(base_dir, llm_config_path) if not os.path.isabs(llm_config_path) else llm_config_path
            else:
                full_path = llm_config_path
            
            if yaml is not None:
                with open(full_path, "r", encoding="utf-8") as f:
                    llm_cfg = yaml.safe_load(f) or {}
                print(_ok(f"Loaded from {full_path}"))
            else:
                print(_warn("PyYAML not installed — cannot load external LLM config"))
                llm_cfg = None
        except FileNotFoundError:
            print(_err(f"File not found: {full_path}"))
            llm_cfg = None
        except Exception as e:
            print(_err(f"Failed to load LLM config: {e}"))
            llm_cfg = None
    
    if llm_cfg:
        if not llm_config_path:
            print(_h2("LLM Configuration"))
            print(_kv("source", f"{_DIM}inline in experiment config{_RESET}"))
        print(_kv("default_model", llm_cfg.get("default_model", "gpt-4o")))
        print(_kv("default_temperature", llm_cfg.get("default_temperature", 0.7)))
        print(_kv("default_max_tokens", llm_cfg.get("default_max_tokens", 2048)))
        providers = llm_cfg.get("providers", {})
        if providers:
            print(_kv("providers", f"{len(providers)} configured"))
            for pname, pcfg in providers.items():
                api_key_raw = pcfg.get("api_key", "")
                if api_key_raw and api_key_raw.startswith("${"):
                    key_display = f"{_CYAN}{api_key_raw}{_RESET}"
                elif api_key_raw:
                    key_display = f"{_DIM}(literal, {len(api_key_raw)} chars){_RESET}"
                else:
                    key_display = f"{_DIM}(env var fallback){_RESET}"
                api_base = pcfg.get("api_base", "")
                api_type = pcfg.get("api_type", "openai")
                base_str = f"  base={api_base}" if api_base else ""
                type_str = f"  type={api_type}" if api_type != "openai" else ""
                print(_bullet(f"{_BOLD}{pname}{_RESET}  key={key_display}{base_str}{type_str}"))
    elif not llm_config_path:
        print(_h2("LLM Configuration"))
        print(_kv("status", f"{_DIM}(not specified — will use environment variables){_RESET}"))

    # ------------------------------------------------------------------
    # 3. Topology
    # ------------------------------------------------------------------
    topo_cfg = config.get("topology", {})
    topo: Optional[CommunicationTopology] = None
    flow: Optional[InformationFlowConfig] = None

    if topo_cfg:
        print(_h2("Communication Topology"))
        topo, flow = build_topology_from_config(topo_cfg)

        agents = topo.agent_ids
        print(_kv("agents", f"{len(agents)}  {agents}"))
        print(_kv("directed", topo.directed))

        edges = topo.get_edges()
        print(_kv("edges", f"{len(edges)} directed edge(s)"))

        # Degree table
        print()
        print(f"    {_BOLD}{'Agent':<20} {'Out-degree':>10} {'In-degree':>10}{_RESET}")
        print(f"    {'─' * 42}")
        for a in agents:
            out_d = topo.out_degree(a)
            in_d = topo.in_degree(a)
            out_str = f"{_GREEN}{out_d}{_RESET}" if out_d > 0 else f"{_DIM}0{_RESET}"
            in_str = f"{_CYAN}{in_d}{_RESET}" if in_d > 0 else f"{_DIM}0{_RESET}"
            print(f"    {a:<20} {out_str:>19} {in_str:>19}")

        # Adjacency matrix
        print()
        print(f"    {_BOLD}Adjacency Matrix:{_RESET}")
        _print_matrix(agents, topo.get_adjacency_matrix())

        # Edge list (readable)
        print()
        print(f"    {_BOLD}Edge List:{_RESET}")
        for s, r in edges:
            print(_bullet(f"{s} → {r}"))

    # ------------------------------------------------------------------
    # 4. Information Flow
    # ------------------------------------------------------------------
    if flow:
        print(_h2("Information Flow"))
        print(_kv("entry_nodes", flow.entry_nodes))
        print(_kv("exit_nodes", flow.exit_nodes))
        print(_kv("cyclic", f"{_GREEN}True (loops){_RESET}" if flow.cyclic else f"{_YELLOW}False (one-shot pipeline){_RESET}"))

        if flow.flow_order:
            print(_kv("flow_order", f"{flow.num_stages} stage(s)"))
            print()
            print(f"    {_BOLD}Stages:{_RESET}")
            for idx, stage in enumerate(flow.stages):
                marker = "↻" if (idx == flow.num_stages - 1 and flow.cyclic) else " "
                print(f"      {_DIM}[{idx}]{_RESET} {_stage_repr(stage)}  {_DIM}{marker}{_RESET}")
            print()
            print(f"    {_BOLD}Flow Diagram:{_RESET}")
            print(f"      {_flow_diagram(flow.stages)}")
            if flow.cyclic:
                print(f"      {_DIM}↻ (loops back to stage 0){_RESET}")

            # Warn about repeated agents across stages
            all_flat = flatten_flow_order(flow.stages)
            seen = {}
            for a in all_flat:
                seen[a] = seen.get(a, 0) + 1
            repeated = {a: c for a, c in seen.items() if c > 1}
            if repeated:
                print()
                for a, c in repeated.items():
                    stages_at = [
                        i for i, st in enumerate(flow.stages)
                        if a in stage_agents(st)
                    ]
                    print(_warn(
                        f"Agent \"{a}\" appears in {c} stages: {stages_at}. "
                        f"It will speak {c} time(s) per round."
                    ))

        # Stop conditions
        if flow.stop_conditions:
            print()
            print(f"    {_BOLD}Stop Conditions:{_RESET}")
            for sc in flow.stop_conditions:
                params = ", ".join(f"{k}={v}" for k, v in sc.parameters.items())
                print(_bullet(f"{sc.condition_type.value}  ({params})"))

        # Trigger
        if flow.trigger:
            params = ", ".join(f"{k}={v}" for k, v in flow.trigger.parameters.items()) if flow.trigger.parameters else ""
            print(_kv("trigger", f"{flow.trigger.trigger_type.value}  {_DIM}{params}{_RESET}"))

        # Named sub-flows
        if flow.flows:
            print()
            print(f"    {_BOLD}Named Sub-Flows ({len(flow.flows)}):{_RESET}")
            for fp in flow.flows:
                diagram = _flow_diagram(fp.order)
                desc = f"  {_DIM}— {fp.description}{_RESET}" if fp.description else ""
                print(f"      {_MAGENTA}{fp.flow_id}{_RESET}: {diagram}{desc}")

        # Validation checks
        print()
        if flow.cyclic:
            overlap = set(flow.entry_nodes) & set(flow.exit_nodes)
            if overlap:
                print(_ok(f"Cyclic validation: entry ∩ exit = {overlap}"))
            else:
                print(_err("Cyclic validation FAILED: entry ∩ exit = ∅"))
        else:
            if set(flow.entry_nodes) != set(flow.exit_nodes):
                print(_ok("Acyclic validation: entry ≠ exit"))
            else:
                print(_warn("Acyclic flow but entry == exit. Consider cyclic: true?"))

    # ------------------------------------------------------------------
    # 5. Simulated Speaker Sequence
    # ------------------------------------------------------------------
    proto_cfg = config.get("protocol", {})
    agent_cfgs = config.get("agents", [])
    all_agent_ids = topo_cfg.get("agents", []) if topo_cfg else [a["agent_id"] for a in agent_cfgs]

    if topo and flow and proto_cfg:
        sim_label = (
            "Simulated Speaker Sequence (≤ 3 rounds)"
            if flow.cyclic
            else "Simulated Speaker Sequence (single pipeline pass)"
        )
        print(_h2(sim_label))
        proto_type = proto_cfg.get("type", "")
        proto_params = {k: v for k, v in proto_cfg.items() if k != "type"}

        steps = _simulate_speakers(topo, flow, proto_type, proto_params, all_agent_ids)
        if steps:
            prev_round = -1
            for s in steps:
                if s["round"] != prev_round:
                    if prev_round >= 0:
                        print()
                    print(f"    {_BOLD}Round {s['round']}:{_RESET}")
                    prev_round = s["round"]
                stage_str = f" {_DIM}(stage {s['stage']}){_RESET}" if s["stage"] is not None else ""
                listeners_str = ", ".join(s["listeners"]) if s["listeners"] else f"{_DIM}(none){_RESET}"
                print(f"      {_BLUE}{s['speaker']:<20}{_RESET} → {listeners_str}{stage_str}")
        else:
            print(_warn(f"Could not simulate: unknown protocol type \"{proto_type}\""))

    # ------------------------------------------------------------------
    # 6. Protocol
    # ------------------------------------------------------------------
    if proto_cfg:
        print(_h2("Protocol"))
        print(_kv("type", proto_cfg.get("type", "(not specified)")))
        for k, v in proto_cfg.items():
            if k != "type":
                print(_kv(k, v))

    # ------------------------------------------------------------------
    # 7. Environment
    # ------------------------------------------------------------------
    env_cfg = config.get("environment", {})
    if env_cfg:
        print(_h2("Environment"))
        print(_kv("name", env_cfg.get("name", "(unnamed)")))
        print(_kv("type", env_cfg.get("type", "(not specified)")))
        print(_kv("max_rounds", env_cfg.get("max_rounds", "—")))
        print(_kv("num_agents", env_cfg.get("num_agents", "—")))
        params = env_cfg.get("parameters", {})
        if params:
            print(_kv("parameters", ""))
            for k, v in params.items():
                print(_bullet(f"{k}: {v}"))

    # ------------------------------------------------------------------
    # 8. Agents
    # ------------------------------------------------------------------
    if agent_cfgs:
        print(_h2(f"Agents ({len(agent_cfgs)})"))
        print()
        print(f"    {_BOLD}{'ID':<20} {'Role':<15} {'Model':<18} {'Objective':<15}{_RESET}")
        print(f"    {'─' * 68}")
        for a in agent_cfgs:
            agent_id = a.get("agent_id", "?")
            role = a.get("role", "—")
            model = a.get("model", "—")
            obj = a.get("objective", "—")
            print(f"    {agent_id:<20} {role:<15} {model:<18} {obj:<15}")
        # Check if any agent has system_prompt
        has_prompts = [a["agent_id"] for a in agent_cfgs if a.get("system_prompt")]
        if has_prompts:
            print()
            print(f"    {_DIM}Agents with system_prompt: {has_prompts}{_RESET}")
        # Check per-agent LLM overrides
        has_overrides = [
            a["agent_id"] for a in agent_cfgs
            if a.get("temperature") is not None
            or a.get("max_tokens") is not None
            or a.get("api_key")
            or a.get("api_base")
            or a.get("provider")
        ]
        if has_overrides:
            print(f"    {_DIM}Agents with per-agent LLM overrides: {has_overrides}{_RESET}")

    # ------------------------------------------------------------------
    # 9. Risks
    # ------------------------------------------------------------------
    risks_cfg = config.get("risks", [])
    if risks_cfg:
        print(_h2(f"Risk Detectors ({len(risks_cfg)})"))
        for r in risks_cfg:
            rtype = r.get("type", "?")
            params = r.get("parameters", {})
            params_str = ", ".join(f"{k}={v}" for k, v in params.items()) if params else ""
            print(_bullet(f"{_MAGENTA}{rtype}{_RESET}  {_DIM}{params_str}{_RESET}"))

    # ------------------------------------------------------------------
    # 10. Evaluation
    # ------------------------------------------------------------------
    eval_cfg = config.get("evaluation", {})
    metrics = eval_cfg.get("metrics", [])
    if metrics:
        print(_h2(f"Evaluation Metrics ({len(metrics)})"))
        for m in metrics:
            mname = m.get("name", "?")
            mtype = m.get("type", "?")
            print(_bullet(f"{mname}  {_DIM}({mtype}){_RESET}"))

    # ------------------------------------------------------------------
    # 11. Seeds
    # ------------------------------------------------------------------
    seeds = config.get("seeds")
    if seeds:
        print(_h2("Reproducibility"))
        print(_kv("seeds", seeds))
        if flow and not flow.cyclic and task_cfg:
            task = TaskConfig.from_dict(dict(task_cfg))
            n_inputs = task.num_inputs if task.num_inputs > 0 else 1
            print(_kv("total runs", f"{seeds} seeds × {n_inputs} input(s) = {seeds * n_inputs} pipeline executions"))
        else:
            print(_kv("total runs", f"{seeds} episode(s)"))

    print()


# ======================================================================
# CLI entry point
# ======================================================================

def main() -> None:
    if yaml is None:
        print(_err("PyYAML is required.  Install with: pip install pyyaml"))
        sys.exit(1)

    parser = argparse.ArgumentParser(
        description="Inspect a MAS-Risk-Toolkit YAML experiment config.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Example:\n  python -m risklab.inspect_config experiments/configs/example_tacit_collusion.yaml",
    )
    parser.add_argument(
        "config",
        help="Path to the YAML experiment config file.",
    )
    args = parser.parse_args()
    inspect_config(args.config)


if __name__ == "__main__":
    main()
