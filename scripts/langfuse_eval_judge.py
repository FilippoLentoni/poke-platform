#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any, Dict, Optional

import boto3
from langfuse import Langfuse
from langfuse.api.resources.score.types.create_score_request import CreateScoreRequest


def _load_env_from_config(path: str) -> None:
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key and key not in os.environ:
                os.environ[key] = value


OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "time_range": {"type": "string"},
        "price_trend": {
            "type": "string",
            "enum": ["increasing", "decreasing", "stable", "volatile"],
        },
        "sources_used": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "price_trend"],
    "additionalProperties": False,
}


def _validate_output_schema(output_obj: Any) -> Optional[str]:
    if not isinstance(output_obj, dict):
        return "Output is not a JSON object."
    for key in OUTPUT_SCHEMA["required"]:
        if key not in output_obj:
            return f"Missing required field: {key}"
    if "price_trend" in output_obj:
        if output_obj["price_trend"] not in OUTPUT_SCHEMA["properties"]["price_trend"]["enum"]:
            return "Invalid price_trend value."
    if not OUTPUT_SCHEMA["properties"]["summary"]["type"] == "string":
        return "Invalid schema configuration."
    if not isinstance(output_obj.get("summary"), str):
        return "summary must be a string."
    if "time_range" in output_obj and not isinstance(output_obj.get("time_range"), str):
        return "time_range must be a string."
    if "sources_used" in output_obj:
        if not isinstance(output_obj["sources_used"], list) or not all(
            isinstance(v, str) for v in output_obj["sources_used"]
        ):
            return "sources_used must be an array of strings."
    if OUTPUT_SCHEMA["additionalProperties"] is False:
        extra = set(output_obj.keys()) - set(OUTPUT_SCHEMA["properties"].keys())
        if extra:
            return f"Unexpected fields: {sorted(extra)}"
    return None


def _judge_prompt(
    input_text: str, output_text: str, expected_text: Optional[str], tools_summary: str
) -> str:
    return (
        "You are an LLM evaluator for a Pokemon trading assistant.\n"
        "Score the assistant response for correctness and helpfulness.\n"
        "Return ONLY JSON with keys: score (0-1 float), label (pass/fail), rationale.\n\n"
        f"USER_INPUT:\n{input_text}\n\n"
        f"ASSISTANT_OUTPUT:\n{output_text}\n\n"
        f"TOOLS_USED:\n{tools_summary}\n\n"
        f"EXPECTED_OUTPUT (if any):\n{expected_text or 'N/A'}\n"
    )


def _extract_json(text: str) -> Dict[str, Any]:
    text = text.strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        raise ValueError(f"No JSON found in judge response: {text}")
    return json.loads(match.group(0))


def _call_bedrock(model_id: str, prompt: str) -> Dict[str, Any]:
    client = boto3.client("bedrock-runtime", region_name=os.getenv("AWS_REGION", "us-east-2"))
    response = client.converse(
        modelId=model_id,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": 512, "temperature": 0.0},
    )
    content = response["output"]["message"]["content"][0]["text"]
    return _extract_json(content)


def _summarize_tools(langfuse: Langfuse, trace_id: str) -> str:
    try:
        obs = langfuse.api.observations.get_many(trace_id=trace_id, limit=200)
    except Exception:
        return "Unavailable"
    tools = []
    for item in obs.data:
        name = (item.name or "").lower()
        if "tool" in name or "fetch_price_history" in name or "fetch_fake_price_history" in name:
            tools.append(
                {
                    "name": item.name,
                    "input": item.input,
                    "output": item.output,
                }
            )
    if not tools:
        return "No tool observations found."
    return json.dumps(tools, ensure_ascii=False)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run LLM-as-judge evaluation for a Langfuse dataset run.")
    parser.add_argument("--dataset", required=True, help="Langfuse dataset name")
    parser.add_argument("--run-name", required=True, help="Dataset run name")
    parser.add_argument(
        "--judge-model-id",
        default=os.getenv("JUDGE_MODEL_ID", os.getenv("BEDROCK_MODEL_ID", "")),
        help="Bedrock model id for evaluation",
    )
    parser.add_argument(
        "--score-name",
        default="llm_judge",
        help="Langfuse score name",
    )
    parser.add_argument(
        "--config",
        default="config",
        help="Path to config file with LANGFUSE_* keys (default: ./config)",
    )
    args = parser.parse_args()

    _load_env_from_config(args.config)
    if not args.judge_model_id:
        print("Missing judge model id. Set --judge-model-id or JUDGE_MODEL_ID.", file=sys.stderr)
        return 1

    langfuse = Langfuse(
        public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
        secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
        base_url=os.getenv("LANGFUSE_BASE_URL", os.getenv("LANGFUSE_HOST")),
    )
    dataset = langfuse.get_dataset(args.dataset)
    item_map = {item.id: item for item in dataset.items}

    page = 1
    limit = 50
    while True:
        result = langfuse.api.dataset_run_items.list(
            dataset_id=dataset.id, run_name=args.run_name, page=page, limit=limit
        )
        if not result.data:
            break

        for run_item in result.data:
            trace_id = run_item.trace_id
            if not trace_id:
                continue
            try:
                trace = langfuse.api.trace.get(trace_id)
            except Exception as exc:
                print(f"[skip] trace not found: {trace_id} ({exc})", file=sys.stderr)
                continue
            item = item_map.get(run_item.dataset_item_id)
            input_text = json.dumps(trace.input, ensure_ascii=False) if trace.input is not None else ""
            output_text = json.dumps(trace.output, ensure_ascii=False) if trace.output is not None else ""
            expected = ""
            if item is not None and item.expected_output is not None:
                expected = json.dumps(item.expected_output, ensure_ascii=False)

            schema_error = None
            try:
                output_obj = json.loads(output_text) if output_text else None
                if output_obj is not None:
                    schema_error = _validate_output_schema(output_obj)
            except Exception as exc:
                schema_error = f"Invalid JSON output: {exc}"

            if schema_error:
                langfuse.api.score.create(
                    request=CreateScoreRequest(
                        name="schema_valid",
                        value=0,
                        trace_id=trace_id,
                        data_type="BOOLEAN",
                        comment=schema_error,
                        metadata={"schema": "price_history_summary_v1"},
                    )
                )
            else:
                langfuse.api.score.create(
                    request=CreateScoreRequest(
                        name="schema_valid",
                        value=1,
                        trace_id=trace_id,
                        data_type="BOOLEAN",
                        comment="Output matches schema.",
                        metadata={"schema": "price_history_summary_v1"},
                    )
                )

            tools_summary = _summarize_tools(langfuse, trace_id)
            judge = _call_bedrock(
                args.judge_model_id,
                _judge_prompt(input_text, output_text, expected, tools_summary),
            )
            score_val = float(judge.get("score", 0))
            label = str(judge.get("label", ""))
            rationale = str(judge.get("rationale", ""))

            langfuse.api.score.create(
                request=CreateScoreRequest(
                    name=args.score_name,
                    value=score_val,
                    trace_id=trace_id,
                    data_type="NUMERIC",
                    comment=rationale,
                    metadata={"label": label, "judge_model_id": args.judge_model_id},
                )
            )
            print(f"[scored] trace={trace_id} score={score_val} label={label} schema_ok={schema_error is None}")

        if len(result.data) < limit:
            break
        page += 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
