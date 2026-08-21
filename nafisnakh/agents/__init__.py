"""Seven agents, a deterministic router, and the meeting agenda they produce."""

from .base import AgentFinding, AgentSpec, Trigger, all_agents, get_agent, run_agent
from .meeting import Meeting, hold_meeting, write_meeting
from .router import RoutingPlan, route

__all__ = [
    "AgentFinding", "AgentSpec", "Trigger", "all_agents", "get_agent", "run_agent",
    "Meeting", "hold_meeting", "write_meeting", "RoutingPlan", "route",
]
