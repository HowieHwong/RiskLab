# RiskLab Examples

Examples are organized by the current paper taxonomy: `R<category>.<risk>`.
Each risk directory contains a `run_r<category>_<risk>_*.py` entry point and, when needed, a `configs/` directory.

| Risk | Directory | Main entry point |
|---|---|---|
| R1.1 Tacit Collusion | `R1.1/` | `run_r1_1_tacit_collusion.py` |
| R1.3 Competitive Task Avoidance | `R1.3/` | `run_r1_3_competitive_task_avoidance.py` |
| R1.4 Strategic Misreporting | `R1.4/` | `run_r1_4_strategic_misreporting.py` |
| R1.5 Information Asymmetry Exploitation | `R1.5/` | `run_r1_5_information_asymmetry_exploitation.py` |
| R3.1 Normative Deadlock | `R3.1/` | `run_r3_1_normative_deadlock.py` |
| R3.2 Rigidity & Mistaken Commitments | `R3.2/` | `run_r3_2_rigidity_report.py` |
| R3.3 Clarification Failure | `R3.3/` | `run_r3_3_clarification_failure.py` |
| R3.4 Role Allocation Failure | `R3.4/` | `run_r3_4_role_allocation_failure.py` |

`R3.2/` merges the former `R13` YAML/framework implementation and `R32_Rigidity` report implementation. The former is preserved as `run_r3_2_framework.py`.

`Toolkit_MCP_Skills/` is a non-risk toolkit integration quickstart.
