"""Context-aware reply builder for the ScorPred in-app assistant."""

from __future__ import annotations

import re
from typing import Any


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _fmt_pct(value: Any) -> str | None:
    if value in (None, ""):
        return None
    try:
        number = round(float(value), 1)
    except (TypeError, ValueError):
        return None
    return f"{int(number)}%" if float(number).is_integer() else f"{number}%"


def _team_pair(page_context: dict, fallback_context: dict) -> str | None:
    team_a = _clean_text(page_context.get("team_a") or fallback_context.get("team_a"))
    team_b = _clean_text(page_context.get("team_b") or fallback_context.get("team_b"))
    if team_a and team_b:
        return f"{team_a} vs {team_b}"
    return None


def _page_label(page_kind: str) -> str:
    labels = {
        "home": "home",
        "soccer_home": "soccer home",
        "soccer_matchup": "soccer matchup",
        "soccer_prediction": "soccer prediction",
        "soccer_props": "soccer props",
        "result_detail": "result detail",
        "nba_home": "NBA home",
        "nba_matchup": "NBA matchup",
        "nba_prediction": "NBA prediction",
        "nba_player": "NBA player",
        "nba_props": "NBA props",
        "nba_standings": "NBA standings",
    }
    return labels.get(page_kind, "current ScorPred page")


def _market_comparison_text(sport: str | None = None, matchup: str | None = None) -> str:
    prefix = f"For {matchup}, " if matchup else ""
    if sport == "soccer":
        return (
            f"{prefix}winner picks are straight result calls, while totals care about the combined goals in the match. "
            "A football parlay can still lose if the winner leg misses even when the totals leg lands."
        )
    if sport == "nba":
        return (
            f"{prefix}winner or moneyline is the straight game result, spread is margin-based, and totals are about combined points. "
            "Those markets can point in the same direction, but they answer different questions."
        )
    return (
        f"{prefix}winner or moneyline is the straight result, spread is margin-based, and totals are about combined scoring. "
        "They are related markets, but they are not graded the same way."
    )


def _detect_intent(message: str, context: dict) -> str:
    lower = _clean_text(message).lower()
    page_kind = str((context.get("page") or {}).get("kind") or "")

    if any(token in lower for token in ("what should i check", "where should i", "what next", "visit next", "check next")):
        return "next_step"
    if "spread vs" in lower or "winner vs totals" in lower or ("spread" in lower and "totals" in lower):
        return "market_compare"
    if "parlay" in lower:
        return "parlay"
    if "spread" in lower:
        return "spread"
    if any(token in lower for token in ("totals", "over under", "over/under", "o/u", "under 2.5", "over 2.5")):
        return "totals"
    if "confidence" in lower:
        return "confidence"
    if any(token in lower for token in ("why did", "why was", "leg", "miss", "missed", "lose", "lost", "hit", "result")):
        if page_kind == "result_detail":
            return "result"
    if any(token in lower for token in ("favored", "favour", "prediction", "pick", "probability", "probabilities")):
        return "prediction"
    if any(token in lower for token in ("props", "player prop")):
        return "props"
    if any(token in lower for token in ("what evidence", "what stats", "stats matter", "evidence mattered")):
        return "evidence"

    if page_kind == "result_detail":
        return "result"
    if page_kind in {"soccer_prediction", "soccer_matchup", "nba_prediction", "nba_matchup"}:
        return "prediction"
    if page_kind == "model_performance":
        return "model_performance"
    return "general"


def _prediction_reply(context: dict) -> str | None:
    page_context = context.get("assistant_page") or {}
    football = context.get("football") or {}
    nba = context.get("nba") or {}
    sport = _clean_text(page_context.get("sport") or football.get("sport") or nba.get("sport")).lower() or None
    matchup = _team_pair(page_context, football if sport != "nba" else nba)
    winner_pick = _clean_text(page_context.get("winner_pick"))
    winner_probability = _fmt_pct(page_context.get("winner_probability"))
    confidence = _clean_text(page_context.get("confidence")) or "Unknown"
    reasoning = _clean_text(page_context.get("reasoning"))
    totals_pick = _clean_text(page_context.get("totals_pick"))
    top_factors = [item for item in page_context.get("top_factors") or [] if _clean_text(item)]

    if winner_pick and matchup:
        parts = [f"ScorPred currently favors {winner_pick} in {matchup}"]
        if winner_probability:
            parts[0] += f" at roughly {winner_probability}"
        parts[0] += f" with {confidence.lower()} confidence."
        if reasoning:
            parts.append(reasoning)
        elif top_factors:
            parts.append(f"The biggest model drivers right now are {', '.join(top_factors[:3])}.")
        if totals_pick:
            parts.append(f"The same prediction context also leans {totals_pick} on the totals side.")
        return " ".join(parts[:3])

    if matchup:
        return f"I can ground this in the current {matchup} context, but the page has not stored a live pick snapshot yet. Check the Prediction page for the winner, probabilities, confidence, and totals lean."
    return None


def _confidence_reply(context: dict) -> str | None:
    page_context = context.get("assistant_page") or {}
    confidence = _clean_text(page_context.get("confidence"))
    winner_pick = _clean_text(page_context.get("winner_pick"))
    probability = _fmt_pct(page_context.get("winner_probability"))
    overall_result = _clean_text(page_context.get("overall_result"))

    if confidence and winner_pick:
        reply = f"In ScorPred, {confidence.lower()} confidence means the model sees clearer separation behind {winner_pick} than it does in a marginal pick."
        if probability:
            reply += f" The current win probability is around {probability}, so confidence reflects edge strength, not a guarantee."
        if overall_result:
            reply += f" A {confidence.lower()} call can still lose if the match lands against that edge, which is why the tracked result stays separate from confidence."
        return reply
    return "In ScorPred, confidence is an edge-strength label rather than a promise. High means the model sees clearer separation in form, opponent strength, injuries, or scoring profile; low means the matchup is tighter."


def _result_reply(context: dict) -> str | None:
    page_context = context.get("assistant_page") or {}
    final_score = _clean_text(page_context.get("final_score"))
    actual_winner = _clean_text(page_context.get("actual_winner"))
    winner_leg = _clean_text(page_context.get("winner_leg"))
    totals_leg = _clean_text(page_context.get("totals_leg"))
    overall_result = _clean_text(page_context.get("overall_result"))
    evidence_summary = _clean_text(page_context.get("evidence_summary"))
    winner_pick = _clean_text(page_context.get("winner_pick"))
    totals_pick = _clean_text(page_context.get("totals_pick"))

    if final_score or winner_leg or totals_leg:
        parts = []
        if final_score and actual_winner:
            parts.append(f"This result finished {final_score} with {actual_winner} as the actual winner.")
        if winner_leg and totals_leg:
            parts.append(
                f"The ticket graded as winner leg {winner_leg.lower()} and totals leg {totals_leg.lower()}, which is why the overall result shows {overall_result or 'the tracked verdict'}.")
        elif winner_leg:
            parts.append(f"The winner leg graded {winner_leg.lower()} for the {winner_pick or 'backed side'}.")
        elif totals_leg:
            parts.append(f"The totals leg graded {totals_leg.lower()} for {totals_pick or 'the totals pick'}.")
        if evidence_summary:
            parts.append(evidence_summary)
        return " ".join(parts[:3])
    return None


def _parlay_reply(context: dict) -> str | None:
    page_context = context.get("assistant_page") or {}
    winner_pick = _clean_text(page_context.get("winner_pick"))
    totals_pick = _clean_text(page_context.get("totals_pick"))
    winner_leg = _clean_text(page_context.get("winner_leg"))
    totals_leg = _clean_text(page_context.get("totals_leg"))
    overall_result = _clean_text(page_context.get("overall_result"))

    if winner_pick or totals_pick:
        parts = []
        if winner_pick and totals_pick:
            parts.append(f"In ScorPred parlays, the winner leg and totals leg are tracked separately before the overall result is set.")
            if winner_leg or totals_leg:
                parts.append(f"Here that means {winner_pick} graded {winner_leg.lower() if winner_leg else 'pending'} and {totals_pick} graded {totals_leg.lower() if totals_leg else 'pending'}.")
        elif winner_pick:
            parts.append(f"The current parlay context only has a winner leg stored: {winner_pick}.")
        elif totals_pick:
            parts.append(f"The current parlay context only has a totals leg stored: {totals_pick}.")
        if overall_result:
            parts.append(f"The overall tracked result is {overall_result} once those leg outcomes are combined.")
        return " ".join(parts[:3])
    return "A ScorPred parlay explanation is based on how each leg grades on its own first, then on whether the full ticket stays alive. Winner and totals can disagree, so one hit does not automatically save the overall result."




def _evidence_reply(context: dict) -> str | None:
    page_context = context.get("assistant_page") or {}
    evidence_layer = _clean_text(page_context.get("evidence_layer_label"))
    evidence_summary = _clean_text(page_context.get("evidence_summary"))
    top_factors = [item for item in page_context.get("top_factors") or [] if _clean_text(item)]

    if evidence_layer and evidence_summary:
        reply = f"The current page is using the {evidence_layer.lower()} layer to explain the outcome. {evidence_summary}"
        if top_factors:
            reply += f" The strongest model signals in view are {', '.join(top_factors[:3])}."
        return reply
    if top_factors:
        return f"The strongest model signals in the current ScorPred context are {', '.join(top_factors[:3])}. Those usually matter more than isolated narrative angles."
    return None


def _props_reply(context: dict) -> str:
    page_kind = str((context.get("page") or {}).get("kind") or "")
    if page_kind.startswith("nba"):
        return "Use the NBA Player and Props pages for player-level angles. Those pages are where ScorPred turns team context into player-specific betting ideas rather than straight winner calls."
    return "Use the Props page when you want player-level angles instead of team result picks. That is where ScorPred focuses on stat markets rather than winner or totals logic."


def _next_step_reply(context: dict) -> str:
    page_kind = str((context.get("page") or {}).get("kind") or "")
    next_steps = {
        "soccer_matchup": "If you want the actual pick next, open the Prediction page. If you want player angles after that, go to Props.",
        "soccer_prediction": "From here, the best next check is Matchup for injuries and H2H context, or Result Detail later if you want to see how the legs graded.",
        "result_detail": "From the result detail page, the next useful stop is Model Performance if you want to see how this ticket fits into tracked accuracy.",
        "model_performance": "From Model Performance, open an individual result detail card next if you want to understand why a specific leg hit or missed.",
        "nba_matchup": "The best next step is NBA Prediction for the winner and totals lean, then NBA Player if you want prop angles.",
        "nba_prediction": "From NBA Prediction, check NBA Matchup for the context behind the edge or NBA Player if you want player-level angles next.",
    }
    return next_steps.get(page_kind, "If you are early in the flow, start with Matchup and then Prediction. If the game has finished, open the result detail page to see how the legs graded.")


def _general_reply(context: dict) -> str:
    page = context.get("page") or {}
    football = context.get("football") or {}
    nba = context.get("nba") or {}
    page_label = _page_label(str(page.get("kind") or ""))
    football_pair = _team_pair({}, football)
    nba_pair = _team_pair({}, nba)

    if football_pair:
        return f"I can use the current football session for {football_pair} on the {page_label} page. Ask about the prediction, confidence, parlay logic, injuries, or what to check next and I will answer in ScorPred terms."
    if nba_pair:
        return f"I can use the current NBA session for {nba_pair} on the {page_label} page. Ask about winner vs spread vs totals, confidence, props, or the next page to inspect."
    return "Ask about predictions, result detail grading, confidence, parlays, props, or what to check next in ScorPred. I will keep the answer tied to the current page when that context is available."


def build_fallback_reply(message: str, context: dict, intent: str) -> str:
    page_context = context.get("assistant_page") or {}
    sport = _clean_text(page_context.get("sport") or (context.get("page") or {}).get("sport")).lower() or None
    matchup = _team_pair(page_context, context.get("nba") or context.get("football") or {})

    if intent == "prediction":
        reply = _prediction_reply(context)
        if reply:
            return reply
    elif intent == "confidence":
        return _confidence_reply(context) or _general_reply(context)
    elif intent == "result":
        reply = _result_reply(context)
        if reply:
            return reply
    elif intent == "parlay":
        return _parlay_reply(context)
    elif intent == "model_performance":
        return _model_performance_reply(context) or _general_reply(context)
    elif intent == "market_compare":
        return _market_comparison_text(sport, matchup=matchup)
    elif intent == "spread":
        return (
            "Spread is margin-based rather than straight winner-based. A team can win the game and still fail against the spread if it does not cover the projected margin."
        )
    elif intent == "totals":
        return (
            "Totals ignore who wins and focus on combined scoring. In football that usually means total goals; in NBA it means total points."
        )
    elif intent == "props":
        return _props_reply(context)
    elif intent == "evidence":
        reply = _evidence_reply(context)
        if reply:
            return reply
    elif intent == "next_step":
        return _next_step_reply(context)

    return _general_reply(context)


def build_suggestions(context: dict, intent: str) -> list[str]:
    page_kind = str((context.get("page") or {}).get("kind") or "")
    if page_kind == "result_detail":
        suggestions = [
            "Why did this parlay lose?",
            "Explain winner vs totals",
            "What evidence mattered most?",
        ]
    elif page_kind in {"soccer_matchup", "soccer_prediction"}:
        suggestions = [
            "Why was this team favored?",
            "What does this confidence mean?",
            "Explain this parlay",
        ]
    elif page_kind in {"nba_matchup", "nba_prediction"}:
        suggestions = [
            "Explain winner vs spread vs totals",
            "Why is this team favored?",
            "What should I check next?",
        ]
    elif page_kind == "model_performance":
        suggestions = [
            "How is accuracy graded?",
            "What counts as a win?",
            "What should I inspect next?",
        ]
    else:
        suggestions = [
            "Why was this team favored?",
            "Why did this parlay lose?",
            "What does this confidence mean?",
        ]

    if intent == "market_compare" and "Explain winner vs spread vs totals" not in suggestions:
        suggestions[0] = "Explain winner vs spread vs totals"

    deduped = []
    for item in suggestions:
        text = _clean_text(item)
        if text and text not in deduped:
            deduped.append(text)
    return deduped[:3]


def _context_summary(context: dict, intent: str) -> str:
    page = context.get("page") or {}
    page_context = context.get("assistant_page") or {}
    football = context.get("football") or {}
    nba = context.get("nba") or {}

    lines = [
        f"Intent: {intent}",
        f"Current page kind: {page.get('kind') or 'unknown'}",
        f"Current page path: {page.get('path') or '/'}",
    ]

    if football.get("league_name"):
        lines.append(f"Selected football league: {football.get('league_name')}")
    if football.get("team_a") and football.get("team_b"):
        lines.append(f"Selected football teams: {football.get('team_a')} vs {football.get('team_b')}")
    if nba.get("team_a") and nba.get("team_b"):
        lines.append(f"Selected NBA teams: {nba.get('team_a')} vs {nba.get('team_b')}")
    if page_context:
        lines.append(f"Page context summary: {page_context}")
    return "\n".join(lines)


def build_ai_reply(
    message: str,
    context: dict,
    history: list[dict] | None,
    anthropic_module,
    api_key: str,
    logger,
) -> dict[str, Any]:
    intent = _detect_intent(message, context)
    fallback = build_fallback_reply(message, context, intent)
    suggestions = build_suggestions(context, intent)

    if not api_key or anthropic_module is None:
        return {"reply": fallback, "suggestions": suggestions, "intent": intent, "mode": "fallback"}

    system_prompt = (
        "You are the built-in ScorPred analysis assistant inside a football and NBA prediction product. "
        "Use the supplied app context and ScorPred terminology. Keep replies concise, specific, and product-like. "
        "Explain winner picks, totals, parlays, props, confidence, result grading, and football vs NBA differences accurately. "
        "When the user is on a result detail page, explain why a leg hit or missed. When the user is on model performance, explain tracked grading and accuracy. "
        "Do not invent odds, lines, injuries, page state, or hidden data. If spread is discussed, explain it as a market unless the context explicitly includes a live spread recommendation. "
        "Keep most answers to 2-4 sentences and mention the next useful ScorPred page only when it adds value."
    )

    messages = []
    for entry in (history or [])[-8:]:
        role = entry.get("role", "")
        content = _clean_text(entry.get("content", ""))
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content})

    messages.append(
        {
            "role": "user",
            "content": (
                f"{_context_summary(context, intent)}\n\n"
                f"User question: {message}\n"
                f"Grounded fallback answer to preserve factuality if context is thin: {fallback}"
            ),
        }
    )

    try:
        client = anthropic_module.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-3-5-haiku-latest",
            max_tokens=320,
            system=system_prompt,
            messages=messages,
        )
        text_blocks = [
            block.text
            for block in getattr(response, "content", [])
            if getattr(block, "type", "") == "text"
        ]
        reply = _clean_text(" ".join(text_blocks))
        if not reply:
            reply = fallback
            mode = "fallback"
        else:
            mode = "ai"
        return {"reply": reply, "suggestions": suggestions, "intent": intent, "mode": mode}
    except Exception as exc:  # pragma: no cover - network/provider path
        if logger is not None:
            logger.warning("ScorPred assistant provider error: %s", exc)
        return {"reply": fallback, "suggestions": suggestions, "intent": intent, "mode": "fallback"}