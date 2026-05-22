"""rapid_agent: Gemini-powered research-brief agent with built-in governance."""

from rapid_agent.agent import RapidAgent, run_brief
from rapid_agent.brief import Brief, BriefItem
from rapid_agent.client import GeminiClient, StubClient, get_default_client
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
