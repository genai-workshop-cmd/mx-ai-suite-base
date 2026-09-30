"""Specialist agents and the registry the pipeline dispatches through."""
from __future__ import annotations

from core.models import Phase

from .analysis_agent import AnalysisAgent
from .base import AgentContext, BaseAgent, Composition
from .config_build_agent import ConfigBuildAgent
from .deploy_agent import DeployAgent
from .fdd_agent import FDDAgent
from .integration_agent import IntegrationAgent
from .orchestrator import Orchestrator, RoutingDecision
from .tdd_agent import TDDAgent
from .testing_agent import TestingAgent

#: Phase -> agent class. The pipeline never imports an agent directly.
AGENTS: dict[Phase, type[BaseAgent]] = {
    Phase.ANALYSIS: AnalysisAgent,
    Phase.FDD: FDDAgent,
    Phase.TDD: TDDAgent,
    Phase.BUILD_CONFIG: ConfigBuildAgent,
    Phase.BUILD_INTEGRATION: IntegrationAgent,
    Phase.TEST: TestingAgent,
    Phase.DEPLOY: DeployAgent,
}

__all__ = [
    "AGENTS",
    "AgentContext",
    "AnalysisAgent",
    "BaseAgent",
    "Composition",
    "ConfigBuildAgent",
    "DeployAgent",
    "FDDAgent",
    "IntegrationAgent",
    "Orchestrator",
    "RoutingDecision",
    "TDDAgent",
    "TestingAgent",
]


def agent_for(phase: Phase) -> type[BaseAgent] | None:
    return AGENTS.get(phase)
