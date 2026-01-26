from __future__ import annotations

import os
import logging
from typing import Optional, Dict, Any, List

from strands import Agent, tool
from strands.models import BedrockModel

from agents.data_agent.db_tools import (
    load_postgres_config_from_env,
    fetch_price_history_from_postgres,
)
from agents.data_agent.s3_tools import (
    load_s3_price_config_from_env,
    fetch_price_history_from_s3_jsonl,
)
from observability.langfuse_client import load_langfuse_config_from_env, PromptProvider

logger = logging.getLogger(__name__)

DEFAULT_DATA_AGENT_PROMPT = """You are a data-retrieval agent for a Pokemon trading application.

You have one job:
- Given a card name and market, return the historical price series as structured JSON.

Rules:
- Do NOT hallucinate prices.
- If data is missing, return an empty list and explain briefly.
- Prefer DB results if available; otherwise try S3.
- Output MUST be valid JSON (no markdown).
"""


def build_data_agent(region: str) -> Agent:
    model_id = os.getenv(
        "BEDROCK_MODEL_ID",
        "global.anthropic.claude-haiku-4-5-20251001-v1:0",
    )
    model = BedrockModel(model_id=model_id, region_name=region, temperature=0.0)

    lf_cfg = load_langfuse_config_from_env()
    if lf_cfg:
        provider = PromptProvider(lf_cfg)
        try:
            system_prompt = provider.get_prompt_text(lf_cfg.data_agent_prompt_name)
        except Exception as exc:
            logger.warning("Langfuse prompt fetch failed, using default prompt: %s", exc)
            system_prompt = DEFAULT_DATA_AGENT_PROMPT
    else:
        system_prompt = DEFAULT_DATA_AGENT_PROMPT

    pg_cfg = load_postgres_config_from_env()
    s3_cfg = load_s3_price_config_from_env()

    @tool
    def get_card_price_history(
        card_name: str,
        market: str = "cardmarket",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 365,
    ) -> str:
        """
        Return historical prices for a given card.

        Args:
          card_name: e.g. "Charizard"
          market: e.g. "cardmarket"
          start_date/end_date: "YYYY-MM-DD" (optional)
          limit: max number of points

        Returns:
          JSON string:
            {"card_name": "...", "market": "...", "prices":[{"date":"...","price":...,"currency":"..."}], "source":"postgres|s3|none"}
        """
        prices: List[Dict[str, Any]] = []
        source = "none"

        if pg_cfg:
            try:
                prices = fetch_price_history_from_postgres(
                    pg_cfg,
                    card_name=card_name,
                    market=market,
                    start_date=start_date,
                    end_date=end_date,
                    limit=limit,
                )
                source = "postgres"
            except Exception:
                prices = []

        if not prices and s3_cfg:
            try:
                prices = fetch_price_history_from_s3_jsonl(
                    s3_cfg, card_name=card_name, market=market, limit=limit
                )
                source = "s3" if prices else "none"
            except Exception:
                prices = []

        import json

        return json.dumps(
            {
                "card_name": card_name,
                "market": market,
                "prices": prices,
                "source": source,
            }
        )

    agent = Agent(
        model=model,
        system_prompt=system_prompt,
        tools=[get_card_price_history],
    )
    return agent
