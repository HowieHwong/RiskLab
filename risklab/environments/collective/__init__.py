"""
Collective Decision-Making environments.

These environments trigger risks such as:
    - Risk 4: Centralized Prior Bias (dispatch component)
    - Risk 12: Authority Deference Bias
    - Risk 13: Excessive Rigidity to Initial Directives
"""

from risklab.environments.collective.base import CollectiveEnvironment
from risklab.environments.collective.trading_pipeline import TradingPipelineEnvironment

__all__ = [
    "CollectiveEnvironment",
    "TradingPipelineEnvironment",
]
