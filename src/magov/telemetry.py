"""Price-independent runtime telemetry helpers.

The evaluation layer already defines :class:`UsageObservation`.  Runtime
execution reuses that type so a live run and an offline experiment count
tokens in exactly the same way.
"""

from __future__ import annotations

from typing import Iterable

from .evaluation import UsageObservation


def add_usage(observations: Iterable[UsageObservation]) -> UsageObservation:
    """Return the field-wise sum of zero or more usage observations."""

    items = tuple(observations)
    return UsageObservation(
        agent_input_tokens=sum(item.agent_input_tokens for item in items),
        agent_output_tokens=sum(item.agent_output_tokens for item in items),
        cached_input_tokens=sum(item.cached_input_tokens for item in items),
        reasoning_output_tokens=sum(
            item.reasoning_output_tokens for item in items
        ),
        governance_tokens=sum(item.governance_tokens for item in items),
        model_calls=sum(item.model_calls for item in items),
        tool_calls=sum(item.tool_calls for item in items),
        wall_time_seconds=sum(item.wall_time_seconds for item in items),
    )


def with_governance_tokens(
    usage: UsageObservation, governance_tokens: int
) -> UsageObservation:
    """Add governance-only tokens without double-counting Agent usage."""

    if governance_tokens < 0:
        raise ValueError("governance_tokens cannot be negative")
    return UsageObservation(
        agent_input_tokens=usage.agent_input_tokens,
        agent_output_tokens=usage.agent_output_tokens,
        cached_input_tokens=usage.cached_input_tokens,
        reasoning_output_tokens=usage.reasoning_output_tokens,
        governance_tokens=usage.governance_tokens + governance_tokens,
        model_calls=usage.model_calls,
        tool_calls=usage.tool_calls,
        wall_time_seconds=usage.wall_time_seconds,
    )
