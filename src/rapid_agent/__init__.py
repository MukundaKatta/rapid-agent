"""rapid_agent: Gemini-powered research-brief agent with built-in governance.

The four governance primitives (``BudgetCap``, ``EgressAllowlist``,
``Trace`` and ``cast_json``) live in :mod:`rapid_agent.governance` and depend
only on the standard library, so they import successfully even when the
agent's runtime extras (``requests`` for fetching, ``pydantic`` for typed
output) are not installed.

The agent surface (``RapidAgent``, ``run_brief``, ``Brief`` and the LLM
clients) needs those extras. If they are missing, the names below stay
unbound and accessing them raises a clear :class:`ImportError` explaining
what to install, rather than failing the whole ``import rapid_agent``.
"""

# Governance primitives are stdlib-only and always available.
from rapid_agent.governance import (
    BudgetCap,
    BudgetExceeded,
    EgressAllowlist,
    EgressDenied,
    OutputCastError,
    Trace,
    TraceEvent,
    cast_json,
)

__version__ = "0.1.0"

# The agent, brief models and clients need optional runtime deps
# (requests, pydantic). Import them defensively so the governance layer
# remains usable on its own.
try:
    from rapid_agent.agent import RapidAgent, run_brief
    from rapid_agent.brief import Brief, BriefItem
    from rapid_agent.client import GeminiClient, StubClient, get_default_client

    _has_agent = True
    _agent_import_error: "Exception | None" = None
except ImportError as _e:  # pragma: no cover - exercised only without extras
    _has_agent = False
    _agent_import_error = _e

# Optional Arize Phoenix export (requires arize-phoenix[otel] extra)
try:
    from rapid_agent.phoenix_export import export_trace_to_phoenix  # noqa: F401

    _has_phoenix = True
except ImportError:
    _has_phoenix = False


def __getattr__(name: str):
    """Give a clear error for agent names when runtime extras are missing."""
    agent_names = {
        "RapidAgent",
        "run_brief",
        "Brief",
        "BriefItem",
        "GeminiClient",
        "StubClient",
        "get_default_client",
    }
    if name in agent_names and not _has_agent:
        raise ImportError(
            f"rapid_agent.{name} requires the runtime extras 'requests' and "
            "'pydantic'. Install the package with: pip install rapid-agent "
            f"(original error: {_agent_import_error})"
        )
    raise AttributeError(f"module 'rapid_agent' has no attribute {name!r}")


__all__ = [
    "Brief",
    "BriefItem",
    "BudgetCap",
    "BudgetExceeded",
    "EgressAllowlist",
    "EgressDenied",
    "GeminiClient",
    "OutputCastError",
    "RapidAgent",
    "StubClient",
    "Trace",
    "TraceEvent",
    "cast_json",
    "get_default_client",
    "run_brief",
]
