def generate_proposals(context: dict) -> list[dict]:
    """
    Baseline demo strategy:
    - Creates 3 deterministic proposals.
    Later this will use:
      context["signals"], context["observations"], context["portfolio"]
    """
    return [
        {
            "action": "BUY",
            "asset_id": "pokemon:sv4a:123",
            "qty": 1,
            "target_price": 42.0,
            "confidence": 0.73,
            "rationale": {"why": "Undervalued vs comps", "signals": ["artist_hype:komiya", "momentum:+7d"]},
        },
        {
            "action": "SELL",
            "asset_id": "pokemon:sv3:045",
            "qty": 1,
            "target_price": 18.5,
            "confidence": 0.61,
            "rationale": {"why": "Over fair value; take-profit", "signals": ["spread_widening"]},
        },
        {
            "action": "BUY",
            "asset_id": "pokemon:sv5:201",
            "qty": 2,
            "target_price": 9.9,
            "confidence": 0.58,
            "rationale": {"why": "Meta usage increasing", "signals": ["meta_usage_delta:+12%"]},
        },
    ]
