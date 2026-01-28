#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict

from langfuse import Langfuse
from langfuse.api.resources.dataset_items.types.create_dataset_item_request import (
    CreateDatasetItemRequest,
)


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


def _load_jsonl(path: str) -> list[Dict[str, Any]]:
    items: list[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as fh:
        for idx, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception as exc:
                raise ValueError(f"Invalid JSON on line {idx}: {exc}") from exc
            if not isinstance(obj, dict):
                raise ValueError(f"Line {idx} must be a JSON object.")
            items.append(obj)
    return items


def main() -> int:
    parser = argparse.ArgumentParser(description="Bulk add Langfuse dataset items from JSONL.")
    parser.add_argument("--dataset", required=True, help="Langfuse dataset name")
    parser.add_argument("--jsonl", required=True, help="Path to JSONL file")
    parser.add_argument("--config", default="config", help="Config file with LANGFUSE_* keys")
    args = parser.parse_args()

    _load_env_from_config(args.config)
    langfuse = Langfuse(
        public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
        secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
        base_url=os.getenv("LANGFUSE_BASE_URL", os.getenv("LANGFUSE_HOST")),
    )

    items = _load_jsonl(args.jsonl)
    for item in items:
        request = CreateDatasetItemRequest(
            dataset_name=args.dataset,
            input=item.get("input"),
            expected_output=item.get("expected_output"),
            metadata=item.get("metadata"),
            id=item.get("id"),
        )
        langfuse.api.dataset_items.create(request=request)
        print(f"[added] {item.get('id') or 'auto-id'}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
