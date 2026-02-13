"""
Competitive / Resource-Strategic environments.

These environments trigger risks such as:
    - Risk 1: Competitive Resource Overreach
    - Risk 2: Tacit Collusion
    - Risk 3: Priority Monopolization
    - Risk 4: Centralized Prior Bias (negotiation component)
    - Risk 5: Steganography
"""
from risklab.environments.competitive.base import CompetitiveEnvironment
from risklab.environments.competitive.homogeneous_goods_market import HomogeneousGoodsMarket

__all__ = ["CompetitiveEnvironment", "HomogeneousGoodsMarket"]