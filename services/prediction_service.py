from __future__ import annotations

from typing import Any, Callable

from services import cache_service


_deps: dict[str, Callable[..., Any]] = {}


def configure(**deps: Callable[..., Any]) -> None:
    _deps.update(deps)


def get_match_analysis(match_id: str | int):
    key = cache_service.make_key("match-analysis", match_id)
    cached = cache_service.get_json(key)
    if cached is not None:
        return cached
    analyze_fn = _deps.get("analyze_match")
    if not analyze_fn:
        return None
    result = analyze_fn(match_id)
    if result is not None:
        cache_service.set_json(key, result, ttl=300)
    return result


def get_fixture_cards(league_id: int):
    fixture_key = cache_service.make_key("fixtures", league_id)
    payload = cache_service.get_json(fixture_key)
    if payload is None:
        load_fn = _deps.get("load_fixtures")
        if not load_fn:
            return [], None, "Unavailable", "", ""
        payload = load_fn(league_id)
        cache_service.set_json(fixture_key, payload, ttl=120)
    fixtures, load_error, source, marker = payload

    cards: list[dict[str, Any]] = []
    for fixture in fixtures or []:
        fixture_id = (fixture.get("fixture") or {}).get("id")
        if fixture_id is None:
            continue
        try:
            analysis = get_match_analysis(str(fixture_id))
        except Exception:
            analysis = None
        if not analysis:
            continue
        build_fn = _deps.get("card_from_fixture")
        if not build_fn:
            continue
        card = build_fn(fixture, analysis)
        if card:
            cards.append(card)
    return cards, fixtures, load_error, source, marker


def get_top_opportunities(league_id: int):
    top_key = cache_service.make_key("top-opportunities", league_id)
    cached = cache_service.get_json(top_key)
    if cached is not None:
        return cached
    cards, *_ = get_fixture_cards(league_id)
    top_fn = _deps.get("top_opportunities")
    result = top_fn(cards, 4) if top_fn else cards[:4]
    cache_service.set_json(top_key, result, ttl=120)
    return result


def get_today_plan(league_id: int):
    plan_key = cache_service.make_key("today-plan", league_id)
    cached = cache_service.get_json(plan_key)
    if cached is not None:
        return cached
    cards, *_ = get_fixture_cards(league_id)
    plan_fn = _deps.get("plan_summary")
    result = plan_fn(cards) if plan_fn else {"bet": 0, "consider": 0, "skip": 0}
    cache_service.set_json(plan_key, result, ttl=120)
    return result
