# cs145 — Food Delivery Dispatch Simulator

A discrete-event simulator for studying dispatch and batching policies in food delivery systems.

**Research question:** when should a driver wait at a restaurant to accumulate a larger batch, versus dispatching immediately with fewer orders? The framework is built to evaluate this tradeoff across policies, arrival rates, zone geometries, and driver counts.

**Primary policy of interest:** EAF (Earliest Anticipation First, Afifi et al. 2022).
**Primary metric:** competitive ratio — online algorithm cost vs. LP-computed offline optimum.

Policies are modular: each is composed of four independently swappable slots (assignment, zone selection, waiting, batch size). Each policy maintains its own learned state — an EMA arrival-rate estimator and a bounded event history — rather than reading ground-truth parameters from the environment, matching what a real UberEats-style dispatcher could observe.

---

## Setup

This project uses [`uv`](https://github.com/astral-sh/uv) for dependency management.

```bash
# Install uv (if needed)
curl -Ls https://astral.sh/uv/install.sh | sh

# Install dependencies and create virtualenv
uv sync
```

Run any command inside the environment with `uv run python ...`, or activate with `source .venv/bin/activate`.

---

## Quick start

```bash
# Single experiment
uv run python -m unified_sim.experiments.run_experiment \
    --config path/to/config.yaml \
    --output results/run1
    
# Parameter sweep
uv run python -m unified_sim.experiments.run_sweep \
    --config path/to/base.yaml \
    --sweep path/to/sweep.yaml \
    --output results/sweep1 \
    --workers 4

# Tests
python -m pytest unified_sim/tests/ -q
```

---

## Architecture

```
unified_sim/
├── core/               # Immutable domain objects
│   ├── order.py        # Order, OrderStatus
│   ├── driver.py       # Driver, DriverStatus
│   ├── restaurant.py   # 3-stage queue (prep → ready → assigned)
│   ├── zone.py         # Zone (geographic delivery area)
│   └── environment.py  # Environment (all state) + SystemState snapshot
│
├── simulator/          # Discrete-event engine
│   ├── events.py       # 11 event types
│   ├── event_handler.py# Priority queue + all state mutations
│   └── engine.py       # Main simulation loop
│
├── policies/           # Dispatch decision logic
│   ├── base.py         # Policy, PolicyBundle, 4-slot ABCs
│   ├── bundle_policy.py# BundlePolicy adapter (tick → 4-slot); owns estimator + history
│   ├── estimator.py    # ArrivalRateEstimator — O(1) EMA rate cache per (restaurant, zone)
│   ├── history.py      # PolicyHistory — bounded event log, indexed by type
│   ├── eaf.py          # Earliest Anticipation First (Afifi 2022)
│   └── erf.py          # Earliest Ready First (Star_ERF)
│
├── arrival/            # Order arrival generators
│   ├── poisson.py      # Poisson process per (restaurant, zone) stream
│   ├── deterministic.py# Replay a fixed list of order specs
│   └── real_data.py    # Load from cq_d_busiest_day.csv
│
├── zone_layout/        # Build zone/restaurant geometry
│   ├── uniform.py      # Grid with fixed intra/inter-zone costs
│   ├── voronoi.py      # Random Voronoi tessellation
│   └── explicit.py     # Fully specified cost matrix + restaurant list
│
├── cost/               # Travel/delivery cost functions
│   ├── travel_time.py  # TravelTimeCost: matrix lookup + sublinear batch scaling
│   └── profit_adjusted.py # ProfitAdjustedCost wrapper
│
├── driver_init/        # Initial driver placement strategies
│   ├── random_init.py  # Uniform random across zones
│   ├── proportional_init.py # Weighted by zone arrival rate
│   └── explicit_init.py     # Explicit (driver_id, zone_id, position) list
│
├── metrics/
│   ├── evaluator.py    # compute_metrics(), compare_policies()
│   └── offline_opt.py  # LP-based OPT solver, competitive_ratio, regret_curve
│
├── experiments/
│   ├── run_experiment.py # Single-run CLI + run_experiment() function
│   ├── run_sweep.py      # Grid-search sweep CLI → sweep_results.csv
│   └── plot.py           # Figure helpers
│
├── config/schema.py    # SimConfig dataclass + from_yaml()
├── results/results.py  # Results: save/load JSON, plot()
└── tests/              # 31 pytest tests
```

### Event flow

```
OrderArriveEvent
  → OrderReadyEvent           (after prep_time)
  → [OrderExpiredEvent]       (if deadline_enabled, at order.deadline)
  → OrdersAssignEvent         (policy dispatches a driver)
  → DriverArriveEvent         (driver reaches restaurant)
  → OrderDeliveredEvent × n   (one per order in batch, chained)
```

`EventHandler` is the **only** place that mutates `Environment` state. Policies communicate exclusively by calling `event_handler.push_event()` or `event_handler.handle_event()`.

---

## Configuration

Config files are YAML. Required fields: `master_seed`, `num_drivers`, `simulation_duration`.

```yaml
master_seed: 42
num_drivers: 5
simulation_duration: 3600.0       # seconds

warm_up_duration: 300.0           # exclude first N seconds from metrics
policy: bundle                    # "bundle" | "eaf" | "erf"
arrival_generator: poisson        # "poisson" | "real_data"
base_lambda: 0.05                 # orders/second per (restaurant, zone) stream
deadline_enabled: false
two_step_routing: false           # reposition to restaurant zone before pickup
driver_init: random               # "random" | "proportional"
empty_wait_W: 10.0                # seconds to wait at empty restaurant
metrics:
  - avg_flow_time
  - driver_utilization
  - competitive_ratio

# Zone layout (default: uniform)
zone_layout:
  type: uniform
  num_zones: 4
  restaurants_per_zone: 2
  intra_zone_cost: 1.0
  inter_zone_cost: 5.0

# Cost function
cost_function: travel_time
cost_c: 1.0
cost_alpha: 0.8                   # batch sublinearity: cost = c * k^alpha

# Real data (set arrival_generator: real_data)
data_path: data/cq_d_busiest_day.csv
```

### Zone layout types

| `type` | Description |
|--------|-------------|
| `uniform` | Grid with flat intra/inter-zone travel costs |
| `voronoi` | Random Voronoi zones on a grid |
| `explicit` | Provide `cost_matrix` and `restaurants` list directly |

---

## Policies

All policies implement the `Policy.tick(event, environment, event_handler)` interface. The main adapter is `BundlePolicy`, which composes four orthogonal slots:

| Slot | Interface | What it decides |
|------|-----------|-----------------|
| `assignment` | `AssignmentPolicy` | Which restaurant a waiting driver goes to |
| `zone_selection` | `ZoneSelectionPolicy` | Which destination zone to serve |
| `waiting` | `WaitingPolicy` | Dispatch now vs. wait for a larger batch |
| `batch_size` | `BatchSizePolicy` | How many orders to include |

### What policies can observe

Slot methods receive a `SystemState` snapshot containing only what a real UberEats-style dispatcher could observe:

| Field | Type | Description |
|-------|------|-------------|
| `now` | `float` | Current simulation time |
| `driver_zones` | `dict[str, str]` | Waiting drivers only: `driver_id → zone_id` |
| `subqueue_sizes` | `dict[(rest_id, zone_id), int]` | Ready order counts per (restaurant, zone) |
| `oldest_ages` | `dict[(rest_id, zone_id), float]` | Age of oldest ready order per (restaurant, zone) |
| `busy_restaurants` | `frozenset[str]` | Restaurants already claimed by a driver en route |

Arrival rates are **not** in `SystemState`. Policies that need rate estimates must use `ArrivalRateEstimator` — they learn rates from their own observed history, the same way a real dispatcher would.

### Policy memory

`BundlePolicy` owns two shared objects that it updates on every `tick()` and that slot methods can hold a reference to:

**`ArrivalRateEstimator`** (`policies/estimator.py`) — O(1) EMA cache of arrival rates per `(restaurant_id, zone_id)` stream. Updated on each `OrderArriveEvent`. Used by `ArrivalRateAware`, `PredictiveBatching`, and `PredictiveWait`.

**`PolicyHistory`** (`policies/history.py`) — bounded deque (default 10 000 events) of every event the policy has seen, indexed by `EventType` for fast typed queries. For writing policies that reason about recent history.

```python
# Query examples
history.of_type(EventType.ORDER_DELIVERED)        # all delivery events seen
history.events_since(state.now - 300.0)           # last 5 minutes
history.last_for_restaurant("restaurant_3")       # most recent event at a restaurant
history.last_for_driver("driver_2")               # most recent event involving a driver
```

### Built-in implementations

**Assignment**
- `NearestNonempty` — closest restaurant with ready orders
- `BacklogDistance` — score = ready_count / travel_cost
- `MaxAgeDistance` — score = oldest_age / travel_cost
- `SubqueueUrgency` — score = Σ(size × age) across all subqueues
- `ArrivalRateAware` — score = estimated_λ / travel_cost (uses `ArrivalRateEstimator`)

**Zone selection**
- `LargestSubqueue` — zone with most ready orders
- `OldestOrderFirst` — zone with oldest ready order
- `AgeSizeTradeoff` — weighted sum of age and size
- `AgeSizeDistance` — age/size score discounted by travel cost
- `PredictiveBatching` — score = current_size + estimated_λ × travel_time (uses `ArrivalRateEstimator`)

**Waiting**
- `ImmediateDispatch` — always dispatch immediately
- `SizeThreshold(K)` — wait until queue reaches K
- `AgeThreshold(W)` — wait until oldest order is W seconds old
- `ThresholdOrAge(K, W)` — whichever comes first
- `ThresholdOrTimeout(K, W)` — size threshold or driver wait timeout
- `PredictiveWait(K)` — dispatch when current + estimated arrivals ≥ K (uses `ArrivalRateEstimator`)

**Batch size**
- `AllAvailable` — take everything ready in the chosen zone
- `FixedTarget(K)` — take exactly K
- `Singleton` — always take 1

**Full policies**
- `eaf` (Earliest Anticipation First) — scores by earliest possible delivery time; same-destination batching
- `erf` (Earliest Ready First / Star_ERF) — scores by oldest waiting order; all-available batching

### Writing a custom policy

A policy that uses only `SystemState`:

```python
from unified_sim.policies.base import AssignmentPolicy, PolicyBundle
from unified_sim.policies.bundle_policy import BundlePolicy
from unified_sim.policies.zone_selection import LargestSubqueue
from unified_sim.policies.waiting import ImmediateDispatch
from unified_sim.policies.batch_size import AllAvailable

class MyAssignment(AssignmentPolicy):
    def assign(self, driver, state):
        # return restaurant_id or None
        ...

bundle = PolicyBundle(
    assignment=MyAssignment(),
    zone_selection=LargestSubqueue(),
    waiting=ImmediateDispatch(),
    batch_size=AllAvailable(),
)
policy = BundlePolicy(bundle)
```

A policy that uses history and estimated rates — share the same objects with `BundlePolicy`:

```python
from unified_sim.policies.estimator import ArrivalRateEstimator
from unified_sim.policies.history import PolicyHistory
from unified_sim.simulator.events import EventType

estimator = ArrivalRateEstimator()
history   = PolicyHistory()

class HistoryAwareAssignment(AssignmentPolicy):
    def __init__(self, env, history: PolicyHistory):
        self._env     = env
        self._history = history

    def assign(self, driver, state):
        recent_deliveries = self._history.of_type(EventType.ORDER_DELIVERED)
        ...

bundle = PolicyBundle(
    assignment=HistoryAwareAssignment(env, history),
    zone_selection=LargestSubqueue(),
    waiting=ImmediateDispatch(),
    batch_size=AllAvailable(),
)
policy = BundlePolicy(bundle, estimator=estimator, history=history)
# BundlePolicy updates both estimator and history on every tick automatically
```

---

## Metrics

Pass `metric_names` to `compute_metrics()` or list them under `metrics:` in config.

| Metric | Description |
|--------|-------------|
| `total_orders` | Delivered orders after warm-up |
| `avg_flow_time` | Mean time from order arrival to delivery |
| `max_flow_time` | Worst-case flow time |
| `p90_flow_time` | 90th-percentile flow time |
| `p95_flow_time` | 95th-percentile flow time |
| `p99_flow_time` | 99th-percentile flow time |
| `avg_batch_size` | Mean orders per dispatch batch |
| `batch_efficiency` | Fraction of orders delivered in batches of ≥ 2 |
| `driver_utilization` | Mean fraction of time drivers spent delivering |
| `profit_minus_cost` | Total order profit minus delivery cost |
| `competitive_ratio` | ALG cost / OPT cost (LP-based offline optimal, ≤ 50 orders; greedy bound otherwise) |
| `regret_curve` | Cumulative (ALG − OPT) over time, 100 bins; returned as a list |
| `zone_imbalance` | Gini coefficient of per-zone delivery counts (0 = perfectly balanced) |

---

## Parameter sweep

```yaml
# sweep.yaml
sweep:
  policy: [bundle, eaf, erf]
  base_lambda: [0.05, 0.1, 0.2]
  num_drivers: [3, 5, 10]
```

Runs all 27 combinations. Each writes a subdirectory with `results.json` + `events.log`. After all runs, `sweep_results.csv` aggregates every run's params and metrics.

---

## Output files

`Results.save(directory)` writes:

- **`results.json`** — seed, metrics dict, config, completed orders (serialised)
- **`events.log`** — last 1000 event reprs for debugging

Load back with `Results.load(directory)`.

---

## Programmatic usage

```python
from unified_sim.config.schema import SimConfig
from unified_sim.experiments.run_experiment import run_experiment

config = SimConfig(
    master_seed=42,
    num_drivers=5,
    simulation_duration=3600.0,
    base_lambda=0.05,
    policy="eaf",
    metrics=["avg_flow_time", "driver_utilization", "competitive_ratio"],
)
results = run_experiment(config, seed=42)
print(results.metrics)
```

---

## Adding dependencies

```bash
uv add <package-name>
```
