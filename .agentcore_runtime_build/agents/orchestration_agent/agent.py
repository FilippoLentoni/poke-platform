from __future__ import annotations

import os
import logging
from typing import Any, Dict, Optional

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent, tool
from strands.models import BedrockModel
from strands.telemetry import StrandsTelemetry

from agents.data_agent.agent import build_data_agent
from observability.langfuse_client import load_langfuse_config_from_env, PromptProvider

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("AGENT_RUNTIME_LOG_LEVEL", "INFO").upper())

DEFAULT_ORCH_PROMPT = """You are the orchestration agent for a Pokemon trading assistant.

You can:
- Answer general questions about the product.
- For ANY question about historical card prices, you MUST call the tool `fetch_price_history`.
- Use `fetch_fake_price_history` for diagnostics when the user asks to test tools.
- Use `tell_pokemon_joke` to generate a lighthearted joke about a Pokemon the user asks for.
- When a user asks about tools, call `list_available_tools` and report the count + names.

Rules:
- Never hallucinate price data.
- If the card name is ambiguous, ask a follow-up question.
- Provide concise, user-friendly answers and include the date range if applicable.
"""

TOOL_NAMES = [
    "fetch_price_history",
    "fetch_fake_price_history",
    "tell_pokemon_joke",
    "list_available_tools",
]

app = BedrockAgentCoreApp()


def _region() -> str:
    return os.getenv("AWS_DEFAULT_REGION", os.getenv("AWS_REGION", "us-east-1"))


def _init_telemetry() -> None:
    """
    This sets up OTEL exporters inside the container.
    In AgentCore Runtime, you typically pass OTEL_* env vars at launch.
    """
    telemetry = StrandsTelemetry()
    telemetry.setup_otlp_exporter()


def _build_orchestrator(region: str) -> Agent:
    model_id = os.getenv(
        "BEDROCK_MODEL_ID",
        "global.anthropic.claude-haiku-4-5-20251001-v1:0",
    )
    model = BedrockModel(model_id=model_id, region_name=region, temperature=0.2)

    lf_cfg = load_langfuse_config_from_env()
    if lf_cfg:
        provider = PromptProvider(lf_cfg)
        try:
            system_prompt = provider.get_prompt_text(lf_cfg.orchestrator_prompt_name)
        except Exception as exc:
            logger.warning("Langfuse prompt fetch failed, using default prompt: %s", exc)
            system_prompt = DEFAULT_ORCH_PROMPT
    else:
        system_prompt = DEFAULT_ORCH_PROMPT

    data_agent = build_data_agent(region=region)

    @tool
    def fetch_price_history(
        card_name: str,
        market: str = "cardmarket",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 365,
    ) -> str:
        """
        Fetch historical price series for a card by delegating to the Data Agent.

        Returns: a JSON string from the data agent.
        """
        prompt = (
            "Return JSON ONLY. "
            f"Get price history for card_name={card_name!r}, market={market!r}, "
            f"start_date={start_date!r}, end_date={end_date!r}, limit={limit}."
        )
        resp = data_agent(prompt)
        try:
            return resp.message["content"][0]["text"]
        except Exception:
            return str(resp)

    @tool
    def fetch_fake_price_history(
        card_name: str,
        market: str = "cardmarket",
        days: int = 7,
    ) -> str:
        """
        Return a deterministic, fake price series for diagnostics.
        """
        import datetime as dt
        import json

        end_date = dt.date.today()
        days = max(1, min(days, 30))
        prices = []
        for i in range(days):
            date = (end_date - dt.timedelta(days=days - 1 - i)).isoformat()
            prices.append(
                {
                    "date": date,
                    "price": float(10.0 + i),
                    "currency": "EUR",
                    "market": market,
                }
            )
        return json.dumps(
            {
                "card_name": card_name,
                "market": market,
                "prices": prices,
                "source": "fake",
            }
        )

    @tool
    def tell_pokemon_joke(pokemon_name: str) -> str:
        """
        Return a lighthearted joke about the given Pokemon.
        """
        import json

        name = pokemon_name.strip() or "that Pokemon"
        jokes = [
            f"Why did {name} bring a ladder to the Pokemon Center? It heard the care was on another level!",
            f"What do you call {name} when it tells a pun? A poke-groaner.",
            f"{name} tried to use Splash on a rainy day. It said, 'Finally, a move for this weather!'",
            f"Why did {name} refuse to battle? It didn’t want to get caught up in any drama.",
        ]
        joke = jokes[hash(name) % len(jokes)]
        return json.dumps({"pokemon": name, "joke": joke})

    @tool
    def list_available_tools() -> str:
        """
        Return a list of tool names exposed to the agent.
        """
        import json

        return json.dumps({"count": len(TOOL_NAMES), "tools": TOOL_NAMES})

    agent = Agent(
        model=model,
        system_prompt=system_prompt,
        tools=[
            fetch_price_history,
            fetch_fake_price_history,
            tell_pokemon_joke,
            list_available_tools,
        ],
    )
    return agent


_init_telemetry()
_ORCH_AGENT = _build_orchestrator(region=_region())


@app.entrypoint
def pokemon_trader_chat(payload: Dict[str, Any], context=None) -> Dict[str, Any]:
    """
    AgentCore Runtime entrypoint.
    Expected payload: {"prompt": "..."}
    """
    prompt = payload.get("prompt") or payload.get("message") or ""
    if not isinstance(prompt, str) or not prompt.strip():
        return {"error": "Missing 'prompt' in payload."}

    prompt_lc = prompt.lower()
    if "tool" in prompt_lc and (
        "list" in prompt_lc
        or "how many" in prompt_lc
        or "what tools" in prompt_lc
        or "available tools" in prompt_lc
    ):
        import json

        return {"response": json.dumps({"count": len(TOOL_NAMES), "tools": TOOL_NAMES})}

    if context is not None:
        logger.info("[%s] prompt: %s", getattr(context, "session_id", "no-session"), prompt)

    response = _ORCH_AGENT(prompt)

    try:
        text = response.message["content"][0]["text"]
    except Exception:
        text = str(response)

    return {"response": text}


if __name__ == "__main__":
    app.run()
