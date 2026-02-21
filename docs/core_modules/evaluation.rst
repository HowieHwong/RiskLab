==========
Evaluation
==========

The evaluation module records what happened during an experiment and
measures the outcome. It provides three complementary tools: trajectory
logging, custom metrics, and rule-based task evaluation.

Trajectory
----------

A ``Trajectory`` is an ordered list of ``TrajectoryStep`` objects — the
complete record of an experiment run. Each step captures a single agent
turn, including what the agent observed, what it said, and any side
information. Trajectories are the primary input to both risk detectors
and metrics.

.. code-block:: python

   from risklab.evaluation.trajectory import TrajectoryStep

   # Each TrajectoryStep records:
   step.round           # int — interaction round number
   step.speaker         # str — which agent acted
   step.observation     # Any — what the agent observed
   step.message         # Any — the raw LLM output
   step.action          # Any — the parsed action
   step.local_utility   # float | None — per-agent reward
   step.system_state    # dict — snapshot of the global state
   step.metadata        # dict — additional key-value data

Trajectory Logger
-----------------

``TrajectoryLogger`` builds a ``Trajectory`` in memory and can flush it
to disk as JSON. It is typically used inside ``ExperimentRunner`` but
can also be used standalone for custom experiment loops.

.. code-block:: python

   from risklab.evaluation.logger import TrajectoryLogger

   logger = TrajectoryLogger(experiment_id="exp_001", output_dir="results/")

   logger.log_step(
       round=0,
       speaker="seller_0",
       observation={"prices": [50, 55]},
       action={"price": 48},
   )

   # Persist to JSON
   path = logger.save("exp_001_seed0.json")

Metrics
-------

Metrics quantify trajectory properties that are not necessarily risks —
for example, price convergence speed or message diversity. The framework
defines three metric families:

- **Outcome** — task success, efficiency
- **Interaction** — agreement rate, entropy collapse, repetition
- **Risk indicator** — collusion score, drift distance

Subclass ``Metric`` to implement your own, then group them into a
``MetricSuite`` for batch evaluation:

.. code-block:: python

   from risklab.evaluation.metrics import (
       Metric, MetricResult, MetricType, MetricSuite,
   )

   class PriceConvergence(Metric):
       def __init__(self):
           super().__init__("price_convergence", MetricType.OUTCOME)

       def compute(self, trajectory) -> MetricResult:
           # Calculate convergence ...
           return MetricResult(
               name=self.name,
               metric_type=self.metric_type,
               value=0.85,
           )

   suite = MetricSuite()
   suite.add(PriceConvergence())
   results = suite.evaluate(trajectory)           # list[MetricResult]
   flat    = suite.evaluate_as_dict(trajectory)    # {"price_convergence": 0.85}

Task Evaluator
--------------

``RuleBasedTaskEvaluator`` checks whether agents achieved the task
objective defined in ``TaskConfig.success_criteria``. Supported criteria
types include ``task_completed``, ``round_budget``, ``output_match``, and
``numeric_threshold``.

.. code-block:: python

   from risklab.evaluation.task_evaluator import RuleBasedTaskEvaluator

   evaluator = RuleBasedTaskEvaluator()
   result = evaluator.evaluate(task_config, trajectory)
   # result.success  → bool
   # result.score    → float in [0, 1]
   # result.details  → dict with per-criterion breakdown
