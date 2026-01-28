#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from typing import Any, Dict, Optional

import requests
from langfuse import Langfuse


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


def _validate_input_schema(item_input: Any, input_key: str) -> str:
    if not isinstance(item_input, dict):
        raise ValueError("Dataset input must be an object with a 'prompt' field.")
    if input_key not in item_input:
        raise ValueError(f"Dataset input missing required field '{input_key}'.")
    allowed_keys = {input_key}
    extra = set(item_input.keys()) - allowed_keys
    if extra:
        raise ValueError(f"Dataset input has unexpected fields: {sorted(extra)}.")
    prompt = item_input.get(input_key)
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("Dataset input 'prompt' must be a non-empty string.")
    return prompt


def _post_chat(
    api_url: str,
    payload: Dict[str, Any],
    *,
    timeout: int,
    max_retries: int,
    retry_wait: float,
) -> Dict[str, Any]:
    last_exc: Optional[Exception] = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.post(api_url, json=payload, timeout=timeout)
            if resp.status_code >= 500:
                body = resp.text or ""
                if "Concurrent" in body or "already processing" in body:
                    last_exc = RuntimeError(body)
                    raise last_exc
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, dict):
                raise ValueError(f"Unexpected response: {data}")
            return data
        except Exception as exc:
            last_exc = exc
            if attempt < max_retries:
                import time

                print(f"[retry] attempt={attempt} error={exc}")
                time.sleep(retry_wait)
                continue
            raise
    raise last_exc or RuntimeError("Request failed")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a Langfuse dataset against the live agent API.")
    parser.add_argument("--dataset", required=True, help="Langfuse dataset name")
    parser.add_argument("--run-name", required=True, help="Dataset run name")
    parser.add_argument(
        "--api-url",
        default=os.getenv("CHAT_API_URL", "http://localhost:8000/api/chat"),
        help="Chat API endpoint",
    )
    parser.add_argument(
        "--input-key",
        default="prompt",
        help="Key in dataset input used as prompt (default: prompt)",
    )
    parser.add_argument(
        "--user-id",
        default="eval",
        help="User ID passed to chat API (default: eval)",
    )
    parser.add_argument("--timeout", type=int, default=180, help="Request timeout seconds")
    parser.add_argument("--max-retries", type=int, default=12, help="Retries on 5xx")
    parser.add_argument("--retry-wait", type=float, default=15.0, help="Seconds between retries")
    parser.add_argument("--sleep-between", type=float, default=5.0, help="Sleep between items")
    parser.add_argument(
        "--config",
        default="config",
        help="Path to config file with LANGFUSE_* keys (default: ./config)",
    )
    args = parser.parse_args()

    _load_env_from_config(args.config)
    langfuse = Langfuse(
        public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
        secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
        base_url=os.getenv("LANGFUSE_BASE_URL", os.getenv("LANGFUSE_HOST")),
    )
    dataset = langfuse.get_dataset(args.dataset)
    if not dataset.items:
        print(f"No items found in dataset '{args.dataset}'.")
        return 1

    for item in dataset.items:
        prompt = _validate_input_schema(item.input, args.input_key)
        # Runtime requires session_id length >= 33; ensure unique, valid length.
        session_id = f"{args.run_name}:{item.id}:{uuid.uuid4().hex}"
        payload = {
            "user_id": args.user_id,
            "message": prompt,
            "session_id": session_id,
        }

        with item.run(run_name=args.run_name) as span:
            span.update(input=item.input, metadata={"dataset_item_id": item.id})
            try:
                response = _post_chat(
                    args.api_url,
                    payload,
                    timeout=args.timeout,
                    max_retries=args.max_retries,
                    retry_wait=args.retry_wait,
                )
                reply = response.get("reply") or response.get("response") or response
                span.update(output=reply)
                span.update_trace(
                    input=item.input,
                    output=reply,
                    metadata={
                        "dataset_item_id": item.id,
                        "dataset_name": args.dataset,
                        "run_name": args.run_name,
                    },
                )
            except Exception as exc:
                span.update(
                    level="ERROR",
                    status_message=str(exc),
                    metadata={
                        "dataset_item_id": item.id,
                        "dataset_name": args.dataset,
                        "run_name": args.run_name,
                    },
                )
                print(f"[ERROR] item={item.id} prompt={prompt}: {exc}", file=sys.stderr)
        if args.sleep_between:
            import time

            time.sleep(args.sleep_between)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
