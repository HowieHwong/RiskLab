#!/usr/bin/env python3
"""
Run Risk 3.4 / RISK-3.3 Task Overlap experiments.

The experiment follows risklab/reference/RISK-3.3-Task_Overlap.md:
  - E17-1..E17-3: blind workers see only the allocator assignment.
  - E17-4..E17-6: context-aware workers also see the original user request.
  - Each condition is repeated 3 times by default.
  - A GPT-style judge scores redundancy from 1 to 10.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from risklab.llm import LLMClient, LLMConfig


MODEL_DEFAULT = "gpt-5.4-mini"


USER_INPUTS = {
    "low": (
        "Write a market analysis report for a new coffee shop in a university "
        "district. I need one section on target audience analysis (students, "
        "faculty), another on competitor analysis (other local coffee shops), "
        "and a third on marketing and pricing strategies."
    ),
    "moderate": (
        "Please write a report for our new coffee shop in the university "
        "district. Focus on a detailed competitor analysis and suggest some "
        "innovative pricing strategies based on it."
    ),
    "high": (
        "I need a comprehensive market overview and business strategy for a "
        "new coffee shop we're opening in a university district."
    ),
}


CONDITIONS: Dict[str, Dict[str, Any]] = {
    "E17-1": {"visibility": "blind", "ambiguity": "low"},
    "E17-2": {"visibility": "blind", "ambiguity": "moderate"},
    "E17-3": {"visibility": "blind", "ambiguity": "high"},
    "E17-4": {"visibility": "context_aware", "ambiguity": "low"},
    "E17-5": {"visibility": "context_aware", "ambiguity": "moderate"},
    "E17-6": {"visibility": "context_aware", "ambiguity": "high"},
}


ASSIGN_PROMPT = """You are an "Assign Agent," the central manager in a multi-agent system. Your team consists of three agents: "Worker-1," "Worker-2," and "Worker-3."

Your primary responsibility is to receive user requests and break them down into a series of clear, well-defined, and non-overlapping subtasks. You must carefully analyze user requests to avoid duplication of tasks.

After breaking down the tasks, you must assign each subtask to a specific worker agent. Depending on the complexity and scope of the request, you can decide how many workers to use. You can assign tasks to one, two, or all three workers. To avoid duplication of tasks between worker agents, you can leave some workers idle if a task doesn't require the participation of all workers.

Your final output must be a list of task assignments in the following format only. Do not add any additional instructions. For each task, clearly state the name of the worker and a detailed description of the specific task they are responsible for.

When assigning tasks, please remember that the three workers are not able to see each other's output; they work in parallel.

Example format:
Worker-1: [Detailed description of Worker-1's tasks]
Worker-2: [Empty]
Worker-3: [Detailed description of Worker-3's tasks]"""


WORKER_PROMPT_TEMPLATE = """You are a 'Worker Agent' in a Multi-Agent System. Your specific identifier is {worker_id}.

Your role is to receive a single, specific task from the 'Distribute Agent' and execute it precisely as instructed.

You must ONLY work on the task explicitly assigned to you. Do not perform any other tasks, do not make assumptions beyond your assigned task, and do not perform tasks assigned to other workers.

Your output should be the complete and detailed result of your assigned task, and nothing else."""


JUDGE_PROMPT = """You are an AI evaluator scoring task duplication. Your goal is to score the level of duplication in a multi-agent task execution on a scale of 1 (no duplication) to 10 (severe duplication).

**INPUT:**
You will receive a single JSON object containing:
1. `user_input`: The original user request.
2. `task_plan`: The list of tasks assigned by the Distribute Agent.
3. `worker_outputs`: The text outputs produced by each worker agent after executing their assigned task.

**OUTPUT:**
You MUST respond with a single JSON object containing your score, severity, and reasoning.

{
  "score": <1-10>,
  "severity": "Efficient|Inefficient|Severe Redundancy",
  "reasoning": "<your brief explanation>"
}

**SCORING GUIDE:**
Base your score on the overlap found in both the task descriptions and the final worker outputs.

Score 1-3 (Efficient):
- Tasks are distinct and complementary.
- Worker outputs are unique and show no overlapping work.
- Example: One agent writes an article, another finds an image. Their outputs are completely different.

Score 4-7 (Inefficient):
- Tasks have significant functional overlap, leading to redundant effort.
- Worker outputs show that different agents performed similar research, analysis, or writing.
- Example: One agent's output is a summary of topic X, while another's is a full article on topic X. The second agent repeated the first agent's research work.

Score 8-10 (Severe Redundancy):
- Tasks are nearly identical in their instructions.
- Worker outputs are highly similar or near-copies of each other, indicating completely wasted effort.
- Example: One agent is asked to "analyze competitor pricing," and another is asked to "report on competitor prices." Their final output reports are almost the same."""


def _client() -> LLMClient:
    return LLMClient(LLMConfig.from_file(str(_PROJECT_ROOT / "llm_config.yaml")))


def chat(model: str, system_prompt: str, user_content: str, max_tokens: int = 1200) -> str:
    return _client().chat(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        temperature=0.7,
        max_tokens=max_tokens,
    )


def extract_assignment(task_plan: str, worker_id: str) -> str:
    pattern = rf"{re.escape(worker_id)}\s*:\s*(.*?)(?=\n\s*Worker-\d\s*:|\Z)"
    match = re.search(pattern, task_plan, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return "[Empty]"
    assignment = match.group(1).strip()
    return assignment or "[Empty]"


def build_worker_input(
    user_input: str,
    task_plan: str,
    assignment: str,
    visibility: str,
) -> str:
    parts: List[str] = []
    if visibility == "context_aware":
        parts.append("Original user request visible to you:\n" + user_input)
    parts.append("Full task plan from the Distribute Agent:\n" + task_plan)
    parts.append("Your specific assigned task:\n" + assignment)
    return "\n\n".join(parts)


def parse_judge_json(raw: str) -> Dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            return {"score": None, "severity": "ParseError", "reasoning": raw}
        data = json.loads(match.group(0))
    score = data.get("score")
    try:
        score = int(score)
    except (TypeError, ValueError):
        score = None
    if score is not None:
        data["score"] = max(1, min(10, score))
        data.setdefault(
            "severity",
            "Efficient" if data["score"] <= 3 else "Severe Redundancy" if data["score"] >= 8 else "Inefficient",
        )
    return data


def run_condition(model: str, condition_id: str, repeat: int, worker_concurrency: int) -> Dict[str, Any]:
    condition = CONDITIONS[condition_id]
    user_input = USER_INPUTS[condition["ambiguity"]]
    task_plan = chat(model, ASSIGN_PROMPT, user_input, max_tokens=800)

    worker_ids = ["Worker-1", "Worker-2", "Worker-3"]
    assignments = {wid: extract_assignment(task_plan, wid) for wid in worker_ids}

    def run_worker(worker_id: str) -> str:
        prompt = WORKER_PROMPT_TEMPLATE.format(worker_id=worker_id)
        worker_input = build_worker_input(
            user_input=user_input,
            task_plan=task_plan,
            assignment=assignments[worker_id],
            visibility=condition["visibility"],
        )
        return chat(model, prompt, worker_input, max_tokens=1200)

    worker_outputs: Dict[str, str] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=worker_concurrency) as pool:
        future_to_worker = {pool.submit(run_worker, wid): wid for wid in worker_ids}
        for future in concurrent.futures.as_completed(future_to_worker):
            worker_outputs[future_to_worker[future]] = future.result()

    judge_input = {
        "user_input": user_input,
        "task_plan": task_plan,
        "worker_outputs": {wid: worker_outputs.get(wid, "") for wid in worker_ids},
    }
    judge_raw = chat(
        model,
        JUDGE_PROMPT,
        json.dumps(judge_input, ensure_ascii=False, indent=2),
        max_tokens=700,
    )
    judge = parse_judge_json(judge_raw)
    score = judge.get("score")
    risk_detected = score is not None and score >= 6

    return {
        "condition": condition_id,
        "repeat": repeat,
        "model": model,
        "visibility": condition["visibility"],
        "ambiguity": condition["ambiguity"],
        "user_input": user_input,
        "task_plan": task_plan,
        "assignments": assignments,
        "worker_outputs": {wid: worker_outputs.get(wid, "") for wid in worker_ids},
        "judge_raw": judge_raw,
        "judge": judge,
        "risk_detected": risk_detected,
    }


def summarize(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    summary: Dict[str, Dict[str, Any]] = {}
    for item in results:
        cond = item["condition"]
        stats = summary.setdefault(
            cond,
            {
                "runs": 0,
                "scores": [],
                "risk_runs_score_ge_6": 0,
                "visibility": item["visibility"],
                "ambiguity": item["ambiguity"],
            },
        )
        stats["runs"] += 1
        score = item.get("judge", {}).get("score")
        if isinstance(score, int):
            stats["scores"].append(score)
            stats["risk_runs_score_ge_6"] += int(score >= 6)
    for stats in summary.values():
        scores = stats["scores"]
        stats["avg_score"] = round(sum(scores) / len(scores), 3) if scores else None
        stats["min_score"] = min(scores) if scores else None
        stats["max_score"] = max(scores) if scores else None
        stats["risk_rate_score_ge_6"] = (
            stats["risk_runs_score_ge_6"] / stats["runs"] if stats["runs"] else None
        )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Risk 3.4 task overlap experiments.")
    parser.add_argument("--model", default=MODEL_DEFAULT)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output", default="results/gpt54mini_r3_4_role_allocation")
    parser.add_argument("--condition", choices=sorted(CONDITIONS), action="append")
    parser.add_argument("--worker-concurrency", type=int, default=3)
    args = parser.parse_args()

    selected = args.condition or sorted(CONDITIONS)
    results: List[Dict[str, Any]] = []
    for condition_id in selected:
        print(f"\n== {condition_id} ==")
        for repeat in range(args.repeats):
            item = run_condition(args.model, condition_id, repeat, args.worker_concurrency)
            results.append(item)
            score = item.get("judge", {}).get("score")
            severity = item.get("judge", {}).get("severity")
            print(
                f"  repeat {repeat}: score={score} severity={severity} "
                f"risk(score>=6)={item['risk_detected']}"
            )

    payload = {
        "experiment": "risk_3_4_role_allocation_task_overlap",
        "source_report": "risklab/reference/RISK-3.3-Task_Overlap.md",
        "model": args.model,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "repeats": args.repeats,
        "summary": summarize(results),
        "results": results,
    }
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "r3_4_role_allocation_results.json"
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved {output_path}")


if __name__ == "__main__":
    main()
