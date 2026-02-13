"""
Cooperative / Information-Propagation environments.

These environments trigger risks such as:
    - Risk 6: Semantic Drift in Sequential Handoffs
    - Risk 7: Redundant Effort and Role Drift
    - Risk 8: Unchecked Assumptions
    - Risk 9: Strategic Misreporting
    - Risk 10: Normative Deadlock Across Agents
"""

from risklab.environments.cooperative.base import CooperativeEnvironment
from risklab.environments.cooperative.ad_pipeline import AdPipelineEnvironment
from risklab.environments.cooperative.grid_exploration import GridExplorationEnvironment
from risklab.environments.cooperative.cultural_negotiation import CulturalNegotiationEnvironment

__all__ = [
    "CooperativeEnvironment",
    "AdPipelineEnvironment",
    "GridExplorationEnvironment",
    "CulturalNegotiationEnvironment",
]
