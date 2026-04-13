"""Page-context and chat-assistant helpers."""

from __future__ import annotations

from datetime import datetime


def now_stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def football_data_source(api_client) -> str:
    return (
        "API-Football via RapidAPI"
        if getattr(api_client, "RAPIDAPI_OK", False)
        else "ESPN public football fallback"
    )


def page_context(api_client, data_source: str | None = None, **kwargs) -> dict:
    context = {
        "data_source": data_source or football_data_source(api_client),
        "last_updated": now_stamp(),
    }
    context.update(kwargs)
    return context


def fallback_chat_reply(
    message: str,
    *,
    team_a: dict | None = None,
    team_b: dict | None = None,
) -> str:
    lower = (message or "").strip().lower()
    matchup = f"{team_a['name']} vs {team_b['name']}" if team_a and team_b else "your selected matchup"

    if "props" in lower:
        return (
            f"Use the Props page to generate player lines for {matchup}. Pick a player, "
            "choose markets, and the app will build a bet slip from live stats."
        )
    if "prediction" in lower or "winner" in lower:
        return (
            f"The Prediction page uses the Scorpred Engine - a weighted model combining "
            f"form, H2H, injuries, venue advantage, and opponent strength - to predict {matchup}."
        )
    if "player" in lower:
        return (
            "The Player page compares squad members side by side and can generate prop "
            "ideas from their season profile and opponent context."
        )
    if "nba" in lower:
        return "The NBA section has its own home, matchup, player, prediction, and standings views under /nba."
    return (
        "Ask about matchup analysis, player props, prediction logic, injuries, or where "
        "to find a specific football or NBA view."
    )


def chat_reply(
    message: str,
    *,
    history: list[dict] | None = None,
    anthropic_module=None,
    api_key: str = "",
    team_a: dict | None = None,
    team_b: dict | None = None,
    logger=None,
) -> str:
    if not api_key or anthropic_module is None:
        return fallback_chat_reply(message, team_a=team_a, team_b=team_b)

    system_prompt = (
        "You are the ScorPred assistant - a helpful AI built into a football and NBA prediction app. "
        "You help users navigate the app, understand predictions, interpret stats, and find features. "
        "Key pages: Home (team selection + upcoming fixtures), Matchup (H2H, form, injuries), "
        "Players (squad comparison, prop ideas), Prediction (Poisson model, win probability), "
        "Props (player bet lines with 6-layer stat model), Fixtures (upcoming schedule), "
        "NBA (full NBA section at /nba with standings, matchup, players, predictions), "
        "World Cup (/worldcup). "
        "Be concise (2-3 sentences max), accurate, and friendly. "
        "Do not make up odds or guarantees. If unsure, say so."
    )

    messages = []
    for entry in (history or [])[-8:]:
        role = entry.get("role", "")
        content = entry.get("content", "")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": message})

    try:
        client = anthropic_module.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-3-5-haiku-latest",
            max_tokens=300,
            system=system_prompt,
            messages=messages,
        )
        text_blocks = [
            block.text
            for block in getattr(response, "content", [])
            if getattr(block, "type", "") == "text"
        ]
        reply = " ".join(text_blocks).strip()
        return reply or fallback_chat_reply(message, team_a=team_a, team_b=team_b)
    except Exception as exc:  # pragma: no cover - best-effort integration wrapper
        if logger is not None:
            logger.warning("Claude chat API error: %s", exc)
        return fallback_chat_reply(message, team_a=team_a, team_b=team_b)
