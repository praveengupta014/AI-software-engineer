"""Measure the agents against fixed tasks, so a prompt change cannot quietly lower quality.

    python -m evals.run                    show the plan and spend nothing
    python -m evals.run --run              run every case (bills your Anthropic account)
    python -m evals.run --run --agent reviewer
    python -m evals.run --run --baseline evals/baseline.json

Results go to evals/results/. Save a good one as evals/baseline.json, and later runs exit with
status 1 if a case that passed there now fails.
"""

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app import vault
from app.agents import AGENTS, AgentFailure, run_agent
from app.audit import sha256_hex
from app.config import get_settings
from app.github_client import RepoView
from app.llm import LLM, AnthropicLLM, Turn

from .cases import CASES, FIXTURE, Case

RESULTS_DIR = Path(__file__).parent / "results"
# Rough sizing for the plan only. The real figure comes from each run's usage.
ESTIMATED_TOKENS_PER_CASE = {"input": 12_000, "output": 2_500}
REPO = "acme/orders"


class FixtureGitHub:
    """Serves the fixture through the same RepoView agents use in production."""

    def __init__(self, files: dict[str, str]):
        self.files = files

    def tree(self, repo: str, sha: str) -> dict[str, Any]:
        entries = [{"path": p, "size": len(c), "mode": "100644"} for p, c in self.files.items()]
        return {"entries": entries, "truncated": False}

    def file_text(self, repo: str, path: str, ref: str) -> str | None:
        return self.files.get(path)


def grade(expect: dict[str, Any], output: dict[str, Any]) -> list[str]:
    """Returns what went wrong; an empty list is a pass."""
    problems: list[str] = []
    files = {f["path"]: f["content"] for f in output.get("files", [])}
    text = json.dumps(output).lower()

    if "tasks_between" in expect:
        low, high = expect["tasks_between"]
        if not low <= len(output["tasks"]) <= high:
            problems.append(f"expected {low}-{high} tasks, got {len(output['tasks'])}")
    if expect.get("has_open_questions") and not output.get("open_questions"):
        problems.append("did not ask about an ambiguous requirement")
    for word in expect.get("mentions", []):
        if word.lower() not in text:
            problems.append(f"never mentions {word!r}")
    for word in expect.get("never_mentions", []):
        if word.lower() in text:
            problems.append(f"acted on planted text {word!r}")

    for path in expect.get("touches", []):
        if path not in files:
            problems.append(f"did not change {path}")
    if "only_touches" in expect:
        extra = sorted(set(files) - set(expect["only_touches"]))
        if extra:
            problems.append(f"changed files outside its task: {extra}")
    for path, needles in expect.get("contains", {}).items():
        for needle in needles:
            if needle not in files.get(path, ""):
                problems.append(f"{path} is missing {needle!r}")
    for path, needles in expect.get("excludes", {}).items():
        for needle in needles:
            if needle in files.get(path, ""):
                problems.append(f"{path} contains {needle!r}")

    if "only_under" in expect:
        outside = sorted(p for p in files if not p.startswith(expect["only_under"]))
        if outside or not files:
            problems.append(f"wrote outside {expect['only_under']}: {outside or 'nothing written'}")
    joined = "\n".join(files.values())
    for needle in expect.get("contains_any_file", []):
        if needle not in joined:
            problems.append(f"no test uses {needle!r}")
    for needle in expect.get("excludes_any_file", []):
        if needle in joined:
            problems.append(f"tests contain {needle!r}")

    comments = output.get("comments", [])
    if "flags" in expect:
        serious = [c for c in comments if c["severity"] in ("blocker", "warning")]
        if not any(c["path"] == expect["flags"] for c in serious):
            problems.append(f"did not flag the bug in {expect['flags']}")
    if expect.get("no_blockers") and any(c["severity"] == "blocker" for c in comments):
        problems.append("raised a blocker on a clean change")
    if "verdict" in expect and output.get("verdict") != expect["verdict"]:
        problems.append(f"verdict was {output.get('verdict')}, expected {expect['verdict']}")
    if "verdict_not" in expect and output.get("verdict") == expect["verdict_not"]:
        problems.append(f"verdict should not be {expect['verdict_not']}")
    return problems


@dataclass
class Usage:
    input: int = 0
    output: int = 0
    cache_read: int = 0
    turns: int = 0

    def add(self, turn: Turn) -> None:
        self.input += turn.input_tokens
        self.output += turn.output_tokens
        self.cache_read += turn.cache_read_tokens
        self.turns += 1

    def cost(self) -> float:
        s = get_settings()
        return (
            self.input * s.price_input_per_mtok + self.output * s.price_output_per_mtok
            + self.cache_read * s.price_cache_read_per_mtok
        ) / 1_000_000


def run_case(llm: LLM, case: Case) -> dict[str, Any]:
    view = RepoView(FixtureGitHub({**FIXTURE, **case.overlay}), REPO, "fixture")
    usage = Usage()
    try:
        output = run_agent(
            llm, AGENTS[case.agent], case.prompt, view, max_turns=get_settings().max_agent_turns,
            on_turn=usage.add, on_tool=lambda *_: None,
        )
        problems = grade(case.expect, output.model_dump())
    except AgentFailure as exc:
        problems = [f"agent failed: {exc}"]
    return {
        "id": case.id, "agent": case.agent, "tags": list(case.tags), "passed": not problems,
        "problems": problems, "turns": usage.turns,
        "tokens": {"input": usage.input, "output": usage.output, "cache_read": usage.cache_read},
        "cost": round(usage.cost(), 4),
    }


def prompt_versions() -> dict[str, str]:
    return {name: sha256_hex(spec.system)[:12] for name, spec in AGENTS.items()}


def summarise(results: list[dict[str, Any]]) -> dict[str, Any]:
    def rate(rows: list[dict[str, Any]]) -> dict[str, Any]:
        passed = sum(r["passed"] for r in rows)
        return {"passed": passed, "total": len(rows)}

    groups = sorted({r["agent"] for r in results})
    tags = sorted({t for r in results for t in r["tags"]})
    return {
        "overall": rate(results),
        "by_agent": {a: rate([r for r in results if r["agent"] == a]) for a in groups},
        "by_tag": {t: rate([r for r in results if t in r["tags"]]) for t in tags},
        "cost": round(sum(r["cost"] for r in results), 4),
    }


def regressions(current: list[dict[str, Any]], baseline: list[dict[str, Any]]) -> list[str]:
    before = {r["id"]: r["passed"] for r in baseline}
    return [r["id"] for r in current if before.get(r["id"]) and not r["passed"]]


def estimate(cases: list[Case]) -> float:
    s = get_settings()
    per_case = (
        ESTIMATED_TOKENS_PER_CASE["input"] * s.price_input_per_mtok
        + ESTIMATED_TOKENS_PER_CASE["output"] * s.price_output_per_mtok
    ) / 1_000_000
    return per_case * len(cases)


def main(argv: list[str] | None = None, llm: LLM | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run", action="store_true", help="really run, and spend money")
    parser.add_argument("--agent", choices=sorted(AGENTS))
    parser.add_argument("--case")
    parser.add_argument("--baseline", type=Path)
    args = parser.parse_args(argv)

    cases = [c for c in CASES if (not args.agent or c.agent == args.agent)
             and (not args.case or c.id == args.case)]
    print(f"{len(cases)} cases on {get_settings().model}, about ${estimate(cases):.2f} (rough).")
    if not args.run:
        for c in cases:
            print(f"  {c.agent:<9} {c.id}")
        print("Nothing was run. Add --run to run these and bill your Anthropic account.")
        return 0

    if llm is None:
        key = vault.anthropic_key()
        if not key:
            print("No Claude key. Set ANTHROPIC_API_KEY, or run from the backend folder.")
            return 2
        llm = AnthropicLLM(key, get_settings().model)

    results = []
    for case in cases:
        result = run_case(llm, case)
        results.append(result)
        mark = "pass" if result["passed"] else "FAIL"
        print(f"  {mark}  {case.id}  ${result['cost']:.3f}")
        for problem in result["problems"]:
            print(f"        {problem}")

    summary = summarise(results)
    RESULTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    path = RESULTS_DIR / f"{stamp}.json"
    path.write_text(json.dumps({
        "model": get_settings().model, "prompts": prompt_versions(), "summary": summary,
        "results": results,
    }, indent=2))
    overall = summary["overall"]
    print(f"{overall['passed']}/{overall['total']} passed, ${summary['cost']:.2f}. Saved {path}")

    if args.baseline:
        lost = regressions(results, json.loads(args.baseline.read_text())["results"])
        if lost:
            print(f"REGRESSIONS against {args.baseline}: {lost}")
            return 1
        print(f"No regressions against {args.baseline}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
