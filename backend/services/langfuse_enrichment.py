"""Fetch cost and token data from Langfuse for mission run enrichment.

Mission runs that have a `langfuse_trace_id` can be enriched on read by
looking up the corresponding Langfuse trace and summing token usage across
its GENERATION observations. Cost is read directly from the trace's
server-computed `total_cost` field.

Network/API failures are swallowed — enrichment is best-effort and should
never block a dashboard response.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


def _get_client() -> Any | None:
    try:
        from langfuse import get_client
    except ImportError:
        return None
    try:
        client = get_client()
    except Exception:
        return None
    try:
        if not client.auth_check():
            return None
    except Exception:
        return None
    return client


def _fetch_one(client: Any, trace_id: str) -> dict[str, Any] | None:
    """Fetch one trace from Langfuse and extract cost + aggregated tokens."""
    try:
        trace = client.api.trace.get(trace_id)
    except Exception as exc:
        logger.debug("Langfuse trace fetch failed for %s: %s", trace_id, exc)
        return None

    input_tokens = 0
    output_tokens = 0
    total_tokens = 0
    for obs in getattr(trace, "observations", []) or []:
        usage_details = getattr(obs, "usage_details", None)
        if not isinstance(usage_details, dict):
            continue
        input_tokens += int(usage_details.get("input", 0) or 0)
        output_tokens += int(usage_details.get("output", 0) or 0)
        total_tokens += int(usage_details.get("total", 0) or 0)

    cost_raw = getattr(trace, "total_cost", None)
    cost_usd: float | None
    try:
        cost_usd = float(cost_raw) if cost_raw is not None else None
    except (TypeError, ValueError):
        cost_usd = None

    return {
        "input_tokens": input_tokens or None,
        "output_tokens": output_tokens or None,
        "total_tokens": total_tokens or None,
        "cost_usd": cost_usd,
    }


async def fetch_trace_metrics(trace_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Fetch cost/token metrics for multiple Langfuse traces concurrently.

    Args:
        trace_ids: List of Langfuse trace IDs to look up. Duplicates and
            empty strings are filtered out.

    Returns:
        Mapping of trace_id -> {input_tokens, output_tokens, total_tokens,
        cost_usd}. Missing or failed traces are omitted from the result.
    """
    unique_ids = [tid for tid in {tid for tid in trace_ids if tid}]
    if not unique_ids:
        return {}

    client = _get_client()
    if client is None:
        return {}

    loop = asyncio.get_running_loop()

    async def _fetch(trace_id: str) -> tuple[str, dict[str, Any] | None]:
        data = await loop.run_in_executor(None, _fetch_one, client, trace_id)
        return trace_id, data

    results = await asyncio.gather(*(_fetch(tid) for tid in unique_ids))
    return {tid: data for tid, data in results if data is not None}
