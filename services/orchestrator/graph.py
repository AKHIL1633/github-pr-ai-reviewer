import asyncio
import json
import logging
import os
import re
from typing import Annotated, Literal, Optional, TypedDict
import operator

from langgraph.graph import StateGraph, END
from langgraph.types import Send
from pydantic import BaseModel, ValidationError, field_validator

from diff_utils import chunk_diff, commentable_lines
from llm import CHAT_MODEL, get_client

logger = logging.getLogger(__name__)

MAX_FINDINGS = int(os.environ.get("MAX_FINDINGS", "25"))
SEVERITY_RANK = {"error": 0, "warning": 1, "info": 2}

AGENT_INSTRUCTIONS = {
    "static_analysis": "You are a static analysis tool. Look for code complexity issues, unused variables, dead code, and poor naming.",
    "security": "You are a security scanner. Look for OWASP Top 10 vulnerabilities, hardcoded secrets, SQL/command injection, path traversal, unsafe deserialization, and missing authorization checks.",
    "style": "You are a code style reviewer. Look for formatting, readability, and consistency issues.",
    "architecture": "You are an architecture reviewer. Look for separation of concerns violations, missing error handling, and improper dependency usage.",
}

OUTPUT_RULES = """Review the git diff you are given.
- Only report issues in added lines (lines whose code starts with '+').
- Every diff line is prefixed with its line number in the new file. Use that number for "line".
- Be specific and actionable. Skip anything you are not confident is a real problem.
Respond with a JSON object of the form:
{"findings": [{"file": "<path>", "line": <int>, "severity": "info" | "warning" | "error", "message": "<what is wrong and how to fix it>"}]}
Return {"findings": []} if there is nothing worth flagging."""


class LLMFinding(BaseModel):
    file: str
    line: Optional[int] = None
    severity: Literal["info", "warning", "error"] = "info"
    message: str

    @field_validator("severity", mode="before")
    @classmethod
    def normalize_severity(cls, value):
        value = str(value or "info").lower()
        return {"critical": "error", "high": "error", "medium": "warning", "low": "info"}.get(value, value)

    @field_validator("line", mode="before")
    @classmethod
    def coerce_line(cls, value):
        # Models sometimes answer "12-14" or "L12"; keep the first number.
        if value is None or isinstance(value, int):
            return value
        match = re.search(r"\d+", str(value))
        return int(match.group()) if match else None


def parse_findings(raw: str) -> list[dict]:
    """Parse an LLM response into validated findings, dropping malformed items instead of the whole response."""
    raw = (raw or "").strip()
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    if fenced:
        raw = fenced.group(1).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("LLM returned non-JSON output: %.200s", raw)
        return []

    items = data.get("findings", []) if isinstance(data, dict) else data
    findings = []
    for item in items if isinstance(items, list) else []:
        try:
            findings.append(LLMFinding.model_validate(item).model_dump())
        except ValidationError:
            logger.warning("Dropping malformed finding: %s", item)
    return findings


class GraphState(TypedDict, total=False):
    diff: str
    patterns: list[str]
    chunks: list[str]
    commentable: dict[str, set[int]]
    findings: Annotated[list[dict], operator.add]  # agents append here in parallel
    review: list[dict]  # final, de-duplicated output (no reducer, so merge replaces rather than appends)


def build_system_prompt(agent_name: str, patterns: list[str]) -> str:
    prompt = AGENT_INSTRUCTIONS[agent_name]
    if patterns:
        history = "\n".join(f"- {p}" for p in patterns)
        prompt += f"\n\nThis repository has repeatedly had these issues in past pull requests; pay extra attention to them:\n{history}"
    return f"{prompt}\n\n{OUTPUT_RULES}"


async def call_llm(system_prompt: str, diff_chunk: str) -> list[dict]:
    try:
        response = await get_client().chat.completions.create(
            model=CHAT_MODEL,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": diff_chunk},
            ],
        )
    except Exception:
        # One failed chunk should not throw away the other agents' work.
        logger.exception("LLM call failed")
        return []
    return parse_findings(response.choices[0].message.content)


def prepare_node(state: GraphState) -> dict:
    return {
        "chunks": chunk_diff(state["diff"]),
        "commentable": commentable_lines(state["diff"]),
    }


def make_agent_node(agent_name: str):
    async def node(state: GraphState) -> dict:
        system_prompt = build_system_prompt(agent_name, state.get("patterns", []))
        results = await asyncio.gather(*(call_llm(system_prompt, chunk) for chunk in state["chunks"]))
        return {"findings": [{**f, "agent": agent_name} for chunk in results for f in chunk]}
    return node


def merge_node(state: GraphState) -> dict:
    commentable = state.get("commentable", {})
    seen = set()
    merged = []
    for finding in state.get("findings", []):
        if commentable and finding.get("file") not in commentable:
            continue  # hallucinated path
        key = (finding.get("file"), finding.get("line"), " ".join(str(finding.get("message", "")).lower().split()))
        if key in seen:
            continue
        seen.add(key)
        finding["inline"] = finding.get("line") in commentable.get(finding.get("file"), set())
        merged.append(finding)

    merged.sort(key=lambda f: (SEVERITY_RANK.get(f.get("severity"), 3), f.get("file") or "", f.get("line") or 0))
    return {"review": merged[:MAX_FINDINGS]}


def fan_out(state: GraphState):
    return [Send(name, state) for name in AGENT_INSTRUCTIONS]


def build_graph():
    builder = StateGraph(GraphState)
    builder.add_node("prepare", prepare_node)
    for name in AGENT_INSTRUCTIONS:
        builder.add_node(name, make_agent_node(name))
    builder.add_node("merge", merge_node)

    builder.set_entry_point("prepare")
    builder.add_conditional_edges("prepare", fan_out, list(AGENT_INSTRUCTIONS))
    for name in AGENT_INSTRUCTIONS:
        builder.add_edge(name, "merge")
    builder.add_edge("merge", END)
    return builder.compile()
