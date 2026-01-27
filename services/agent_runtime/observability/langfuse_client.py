from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Optional, Dict, Any

try:
    from langfuse import Langfuse
except Exception:  # pragma: no cover
    Langfuse = None  # type: ignore


@dataclass(frozen=True)
class LangfuseConfig:
    public_key: str
    secret_key: str
    base_url: str = "https://us.cloud.langfuse.com"
    orchestrator_prompt_name: str = "pokemon-orchestrator-system"
    data_agent_prompt_name: str = "pokemon-data-agent-system"
    prompt_label: str = "production"
    prompt_cache_ttl_seconds: int = 60


class PromptProvider:
    """
    Pull-based prompt control:
    - Store/version prompts in Langfuse
    - Agent fetches prompt by (name, label)
    - Cache for TTL to avoid calling Langfuse on every request
    """

    def __init__(self, cfg: LangfuseConfig):
        if Langfuse is None:
            raise RuntimeError(
                "Langfuse SDK not installed. Add `langfuse` to requirements."
            )
        self._cfg = cfg
        # Langfuse SDK renamed base_url -> host in v3.7.0.
        try:
            self._client = Langfuse(
                public_key=cfg.public_key,
                secret_key=cfg.secret_key,
                host=cfg.base_url,
            )
        except TypeError:
            self._client = Langfuse(
                public_key=cfg.public_key,
                secret_key=cfg.secret_key,
                base_url=cfg.base_url,
            )
        self._cache: Dict[str, Dict[str, Any]] = {}

    def _cache_key(self, name: str, label: str) -> str:
        return f"{name}:{label}"

    def get_prompt_text(self, name: str, label: Optional[str] = None) -> str:
        label = label or self._cfg.prompt_label
        key = self._cache_key(name, label)

        now = time.time()
        cached = self._cache.get(key)
        if cached and (now - cached["ts"]) < self._cfg.prompt_cache_ttl_seconds:
            return str(cached["value"])

        prompt_obj = None
        try:
            prompt_obj = self._client.get_prompt(name=name, label=label)
            if hasattr(prompt_obj, "prompt"):
                text = prompt_obj.prompt
            elif hasattr(prompt_obj, "text"):
                text = prompt_obj.text
            elif hasattr(prompt_obj, "content"):
                text = prompt_obj.content
            else:
                text = str(prompt_obj)
        except Exception as exc:
            raise RuntimeError(f"Failed to fetch prompt from Langfuse: {exc}") from exc

        self._cache[key] = {"value": text, "ts": now}
        return str(text)


def load_langfuse_config_from_env() -> Optional[LangfuseConfig]:
    """
    Return None if keys are not set (so you can run without Langfuse in dev).
    """
    pub = os.getenv("LANGFUSE_PUBLIC_KEY")
    sec = os.getenv("LANGFUSE_SECRET_KEY")
    if not pub or not sec:
        return None

    return LangfuseConfig(
        public_key=pub,
        secret_key=sec,
        base_url=os.getenv("LANGFUSE_BASE_URL", "https://us.cloud.langfuse.com"),
        orchestrator_prompt_name=os.getenv(
            "LANGFUSE_ORCH_PROMPT_NAME", "pokemon-orchestrator-system"
        ),
        data_agent_prompt_name=os.getenv(
            "LANGFUSE_DATA_PROMPT_NAME", "pokemon-data-agent-system"
        ),
        prompt_label=os.getenv("LANGFUSE_PROMPT_LABEL", "production"),
        prompt_cache_ttl_seconds=int(os.getenv("LANGFUSE_PROMPT_TTL", "60")),
    )
