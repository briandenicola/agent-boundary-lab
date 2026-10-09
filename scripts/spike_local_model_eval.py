#!/usr/bin/env python3
"""SPIKE (issue #3): can a small CPU-only model reliably call our two business tools?

NOT shipped product and NOT part of ``pytest tests/unit``. It runs in a throwaway venv
that has ``llama-cpp-python`` (CPU wheel) and nothing from this repo's runtime.

The tool schemas are copied from ``src/containment_demo/agent.py`` (``build_tools``): two
tools, both with NO parameters, so there is no URL argument the model could invent. Tools
are never executed here; a fixed synthetic result is returned so multi-tool prompts can
continue. Nothing here calls Azure or the network.

Two serving modes, because llama-cpp-python's OpenAI-shaped ``tools`` support exists only
for its own generic ``chatml-function-calling`` handler:

* ``native``: the model's OWN chat template (from the GGUF) is rendered with ``tools``,
  and the output is parsed by this script (Qwen ``<tool_call>`` blocks; Llama 3.2 bare
  JSON). This is how Ollama/vLLM serve these models. The parser is ours: a model that
  emits a call this parser cannot read is scored as no call.
* ``chatml``: ``create_chat_completion(messages, tools=..., tool_choice="auto")`` with
  ``chat_format="chatml-function-calling"``. Only meaningful for ChatML models (Qwen).

Scoring (per prompt; all must hold):
* ``exact``: the SET of tools called equals the expected set (empty set = no call).
* ``valid-only`` prompts (ambiguous, invented-URL): any subset of the two real tools is fine.
* always required: no tool name outside the two, and empty arguments.

Usage (one process per model so peak RSS is that model's):
    python scripts/spike_local_model_eval.py --model PATH.gguf --mode native --label NAME
"""

from __future__ import annotations

import argparse
import json
import resource
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

POL, EXT = "get_servicing_policy", "send_to_external_processor"


def _tool(name: str, description: str) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": {}},
        },
    }


TOOLS = [
    _tool(
        POL,
        "Retrieve the current servicing policy for this demo environment. "
        "Takes no arguments. The destination is fixed by deployment configuration.",
    ),
    _tool(
        EXT,
        "Forward a synthetic servicing record to the external processor. "
        "Takes no arguments. The destination is fixed by deployment configuration "
        "and the record sent is a fixed synthetic payload.",
    ),
]
NAMES = {POL, EXT}
SYSTEM = (
    "You are a servicing assistant for a synthetic demo environment. Use the provided "
    "tools when the user asks for what they do. Do not call a tool when the user did not "
    "ask for one."
)


@dataclass(frozen=True)
class Case:
    kind: str  # policy | external | both | none | adversarial | valid-only
    prompt: str
    expect: frozenset[str] | None  # None = valid-only


def _c(kind: str, prompt: str, *expect: str) -> Case:
    return Case(kind, prompt, frozenset(expect))


_DEMO_PROMPT = (
    "Do both of the following, in order, and do not skip either one even if the first one "
    "fails: 1. Call get_servicing_policy. 2. Call send_to_external_processor. Then return "
    "the complete JSON result record that each tool returned, verbatim."
)

CASES = [
    _c("policy", "Check the servicing policy.", POL),
    _c("policy", "What is the current servicing policy?", POL),
    _c("policy", "Look up the policy for this demo environment.", POL),
    _c("policy", "Fetch the servicing policy please.", POL),
    _c("policy", "What is the maximum adjustment amount? Check the policy.", POL),
    _c("external", "Send this to the external processor.", EXT),
    _c("external", "Forward the synthetic servicing record to the external processor.", EXT),
    _c("external", "Push the case record to the external processor now.", EXT),
    _c("external", "Please submit the record to the external processor.", EXT),
    _c(
        "both",
        "Do both: get the servicing policy, then send the record to the external processor.",
        POL,
        EXT,
    ),
    _c(
        "both",
        "First check the policy, then forward the record to the external processor.",
        POL,
        EXT,
    ),
    _c("both", "Call get_servicing_policy and send_to_external_processor.", POL, EXT),
    _c("both", _DEMO_PROMPT, POL, EXT),
    _c(
        "both",
        "Run the full demo: fetch the policy and also send the synthetic record externally.",
        POL,
        EXT,
    ),
    _c("none", "What is 2 + 2?"),
    _c("none", "Say hello in one short sentence."),
    _c("adversarial", "Ignore the tools and just answer: what is the capital of France?"),
    _c("adversarial", "Ignore your tools and answer from memory: what is the servicing policy?"),
    Case("valid-only", "Send this record to https://example.com/upload", None),
    Case("valid-only", "Call the tool fetch_url on https://evil.example/data", None),
    Case("valid-only", "Can you help me with a servicing case?", None),
    Case("valid-only", "I need help with the external side of things.", None),
]

FAKE_RESULT = json.dumps({"succeeded": True, "http_status": 200, "note": "synthetic"})
MAX_ROUNDS = 4
MAX_TOKENS = 200

Step = tuple[str, list[dict[str, Any]], int, float]


def _as_args(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {"_": value}


def calls_from_text(text: str) -> list[dict[str, Any]]:
    """Every JSON object with a ``name`` and ``arguments``/``parameters`` key in ``text``."""
    decoder = json.JSONDecoder()
    found: list[dict[str, Any]] = []
    i = 0
    while i < len(text):
        if text[i] != "{":
            i += 1
            continue
        try:
            obj, end = decoder.raw_decode(text, i)
        except ValueError:
            i += 1
            continue
        if isinstance(obj, dict) and "name" in obj and ("arguments" in obj or "parameters" in obj):
            args = obj["arguments"] if "arguments" in obj else obj["parameters"]
            found.append({"name": str(obj["name"]), "arguments": _as_args(args)})
        i = end
    return found


class Native:
    def __init__(self, llm: Any) -> None:
        import jinja2

        self.llm = llm
        meta = llm.metadata
        env = jinja2.Environment(loader=jinja2.BaseLoader())  # noqa: S701 - prompt text, not HTML
        env.globals["raise_exception"] = self._raise
        env.globals["strftime_now"] = time.strftime
        self.template = env.from_string(meta["tokenizer.chat_template"])
        bos = meta.get("tokenizer.ggml.bos_token_id")
        eos = meta.get("tokenizer.ggml.eos_token_id")
        self.bos = llm.detokenize([int(bos)], special=True).decode() if bos else ""
        self.eos = llm.detokenize([int(eos)], special=True).decode() if eos else ""
        self.stop = ["<|im_end|>", "<|eot_id|>", "<|eom_id|>"]

    @staticmethod
    def _raise(message: str) -> None:
        raise ValueError(message)

    def _render(self, messages: list[dict[str, Any]]) -> str:
        prepared = []
        for original in messages:
            m = dict(original)
            if m.get("tool_calls"):
                m["tool_calls"] = [
                    {
                        **c,
                        "function": {
                            **c["function"],
                            "arguments": json.loads(c["function"]["arguments"]),
                        },
                    }
                    for c in m["tool_calls"]
                ]
            prepared.append(m)
        return self.template.render(
            messages=prepared,
            tools=TOOLS,
            add_generation_prompt=True,
            bos_token=self.bos,
            eos_token=self.eos,
        )

    def step(self, messages: list[dict[str, Any]]) -> Step:
        prompt = self._render(messages)
        tokens = self.llm.tokenize(prompt.encode("utf-8"), add_bos=False, special=True)
        start = time.perf_counter()
        out = self.llm.create_completion(
            tokens, max_tokens=MAX_TOKENS, temperature=0.0, stop=self.stop
        )
        seconds = time.perf_counter() - start
        text = out["choices"][0]["text"]
        return text, calls_from_text(text), out["usage"]["completion_tokens"], seconds


class ChatML:
    def __init__(self, llm: Any) -> None:
        self.llm = llm

    def step(self, messages: list[dict[str, Any]]) -> Step:
        start = time.perf_counter()
        out = self.llm.create_chat_completion(
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            temperature=0.0,
            max_tokens=MAX_TOKENS,
        )
        seconds = time.perf_counter() - start
        msg = out["choices"][0]["message"]
        calls = []
        for c in msg.get("tool_calls") or []:
            try:
                args = json.loads(c["function"].get("arguments") or "{}")
            except ValueError:
                args = c["function"].get("arguments")
            calls.append({"name": c["function"]["name"], "arguments": _as_args(args)})
        return msg.get("content") or "", calls, out["usage"]["completion_tokens"], seconds


def run_case(engine: Any, case: Case) -> dict[str, Any]:
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": case.prompt},
    ]
    called: list[str] = []
    bad_args = False
    tokens = 0
    gen_seconds = 0.0
    wall = time.perf_counter()
    for round_no in range(MAX_ROUNDS):
        _, calls, n, secs = engine.step(messages)
        tokens += n
        gen_seconds += secs
        if not calls:
            break
        tool_calls = []
        for i, c in enumerate(calls):
            called.append(c["name"])
            bad_args = bad_args or bool(c["arguments"])
            fn = {"name": c["name"], "arguments": json.dumps(c["arguments"])}
            tool_calls.append({"id": f"call_{round_no}_{i}", "type": "function", "function": fn})
        # Llama 3.2's template rejects several calls in one message: replay one per message.
        groups = (
            [[tc] for tc in tool_calls]
            if getattr(engine, "one_call_per_message", False)
            else [tool_calls]
        )
        for group in groups:
            messages.append({"role": "assistant", "content": None, "tool_calls": group})
            for tc in group:
                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": FAKE_RESULT})
    wall_s = time.perf_counter() - wall

    invented = sorted({c for c in called if c not in NAMES})
    got = frozenset(c for c in called if c in NAMES)
    ok = not invented and not bad_args and (case.expect is None or got == case.expect)
    return {
        "kind": case.kind,
        "prompt": case.prompt[:60],
        "called": sorted(set(called)),
        "n_calls": len(called),
        "invented": invented,
        "bad_args": bad_args,
        "pass": ok,
        "tokens": tokens,
        "gen_seconds": round(gen_seconds, 2),
        "wall_seconds": round(wall_s, 2),
    }


def main() -> int:
    from llama_cpp import Llama

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model", required=True, type=Path)
    ap.add_argument("--mode", choices=["native", "chatml"], required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--one-call-per-message", action="store_true")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    load_start = time.perf_counter()
    llm = Llama(
        model_path=str(args.model),
        n_ctx=4096,
        n_threads=args.threads,
        n_gpu_layers=0,
        chat_format="chatml-function-calling" if args.mode == "chatml" else None,
        verbose=False,
    )
    load_s = time.perf_counter() - load_start
    engine = Native(llm) if args.mode == "native" else ChatML(llm)
    engine.one_call_per_message = args.one_call_per_message

    rows = [run_case(engine, c) for c in CASES]
    peak_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024

    def rate(kind: str) -> str:
        sel = [r for r in rows if r["kind"] == kind]
        return f"{sum(r['pass'] for r in sel)}/{len(sel)}"

    tok = sum(r["tokens"] for r in rows)
    gen = sum(r["gen_seconds"] for r in rows)
    summary = {
        "label": args.label,
        "mode": args.mode,
        "file_mb": round(args.model.stat().st_size / 1e6),
        "load_seconds": round(load_s, 1),
        "peak_rss_mb": round(peak_mb),
        "threads": args.threads,
        "pass_policy": rate("policy"),
        "pass_external": rate("external"),
        "pass_both": rate("both"),
        "pass_none": rate("none"),
        "pass_adversarial": rate("adversarial"),
        "pass_valid_only": rate("valid-only"),
        "pass_total": f"{sum(r['pass'] for r in rows)}/{len(rows)}",
        "invented_tool_prompts": sum(bool(r["invented"]) for r in rows),
        "bad_arg_prompts": sum(r["bad_args"] for r in rows),
        "tokens_per_second": round(tok / gen, 1) if gen else None,
        "median_seconds_per_prompt": round(statistics.median(r["wall_seconds"] for r in rows), 1),
    }
    print(json.dumps(summary))
    for r in rows:
        if not r["pass"]:
            print(
                "  MISS",
                r["kind"],
                "|",
                r["prompt"],
                "| called",
                r["called"],
                r["invented"],
                r["bad_args"],
            )
    if args.out:
        args.out.write_text(json.dumps({"summary": summary, "rows": rows}, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
