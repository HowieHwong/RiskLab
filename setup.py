"""Minimal setup.py for editable installs."""

from setuptools import setup, find_packages

setup(
    name="mas-risk-toolkit",
    version="0.1.0",
    description=(
        "A controlled multi-agent interaction framework for instantiating, "
        "probing, and measuring emergent social risks in LLM-based agent "
        "collectives."
    ),
    author="Yue Huang et al.",
    packages=find_packages(),
    python_requires=">=3.9",
    install_requires=[
        "pyyaml>=6.0",
    ],
    extras_require={
        "openai": ["openai>=1.0"],
        "dev": ["pytest", "ruff"],
    },
)
