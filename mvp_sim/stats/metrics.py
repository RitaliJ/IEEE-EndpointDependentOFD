from __future__ import annotations

import statistics
from mvp_sim.core.environment import Environment
from mvp_sim.core.order import OrderStatus
from mvp_sim.cost_functions.travel_time import AuxInfo
from mvp_sim.stats import _ALL_METRICS, _SUMMARY_METRICS
from ..offline.solvers import OfflineSolver

"""
This file is only ran to analyze the output of experiments.
"""

_NAN = float("nan")

def compute_metrics(
    env:          Environment,
    metric_names: list[str],
    ainfo:        AuxInfo,
    offline_solver: OfflineSolver | None = None,
) -> dict:
    """Compute simulation performance metrics from a completed Environment.

    Filters orders that arrived during warm-up before computing.
    Returns a dict keyed by metric name. Unknown names raise ValueError.
    """
    assert metric_names is not None and len(metric_names) > 0

    warm_up_duration = env.warmup_duration
    horizon = env.horizon

    for name in metric_names:
        if name not in _ALL_METRICS:
            raise ValueError(f"Unknown metric: {name!r}. Valid: {sorted(_ALL_METRICS)}")

    delivered = [
        o for o in env.orders.values()
        if o.arrival_time >= warm_up_duration
        and o.order_status == OrderStatus.DELIVERED
        and o.completion_time is not None
    ]

    result: dict = {}

    # Every order that arrived inside the measurement window. delivered + undelivered
    # partition this set exactly, which is what lets a comparison verify that two
    # policies' flow times are computed over the same population (P1 item 7).
    arrived = [
        o for o in env.orders.values()
        if o.arrival_time >= warm_up_duration
    ]

    if "total_orders" in metric_names:
        result["total_orders"] = len(delivered)

    if "arrived_orders" in metric_names:
        result["arrived_orders"] = len(arrived)

    if "delivered_orders" in metric_names:
        result["delivered_orders"] = len(delivered)

    if "undelivered_orders" in metric_names:
        result["undelivered_orders"] = len(arrived) - len(delivered)

    if "completion_rate" in metric_names:
        result["completion_rate"] = (len(delivered) / len(arrived)) if arrived else _NAN

    if not delivered:
        for name in metric_names:
            result.setdefault(name, _NAN)
        return result

    if "flow_time" in metric_names:
        result["flow_time"] = _summary_stats([o.flow_time() for o in delivered])

    post_warmup_batches = [
        (driver, batch) for driver, batch in env.batches
        if all(o.arrival_time >= warm_up_duration for o in batch)
    ]

    # TODO this does not have the cost for moving between batches which is wrong again...
    travel_costs = [
        sum(env.compute_orders_travel_cost(batch, driver))
        for driver, batch in post_warmup_batches
    ]

    travel_costs += env.driver_pickup_and_reposition_time

    if "travel_time" in metric_names:
        result["travel_time"] = _summary_stats(travel_costs)

    if "avg_batch_size" in metric_names:
        result["avg_batch_size"] = (
            statistics.mean(len(b) for _, b in post_warmup_batches)
            if post_warmup_batches else _NAN
        )

    if "batch_efficiency" in metric_names:
        if not post_warmup_batches:
            result["batch_efficiency"] = _NAN
        else:
            total   = sum(len(b) for _, b in post_warmup_batches)
            batched = sum(len(b) for _, b in post_warmup_batches if len(b) >= 2)
            result["batch_efficiency"] = batched / total

    if "driver_utilization" in metric_names:
        effective_duration = horizon - warm_up_duration
        if effective_duration <= 0:
            result["driver_utilization"] = _NAN
        else:
            utils = [
                busy_time_in_window(d.busy_intervals, warm_up_duration, horizon) / effective_duration
                for d in env.drivers.values()
            ]
            # Guaranteed by construction: merged intervals clipped to the window
            # cannot cover more than the window itself.
            assert all(0.0 <= u <= 1.0 for u in utils), (
                f"driver utilization outside [0,1]: max={max(utils)}"
            )
            result["driver_utilization"] = _summary_stats(utils)

    # The last completion in the run. With draining enabled this is well past the
    # horizon whenever arrivals outpace service.
    completions = [o.completion_time for o in delivered if o.completion_time is not None]
    makespan = max(completions) if completions else horizon

    if "makespan" in metric_names:
        result["makespan"] = makespan

    if "driver_utilization_makespan" in metric_names:
        span = makespan - warm_up_duration
        if span <= 0:
            result["driver_utilization_makespan"] = _NAN
        else:
            utils_m = [
                busy_time_in_window(d.busy_intervals, warm_up_duration, makespan) / span
                for d in env.drivers.values()
            ]
            assert all(0.0 <= u <= 1.0 for u in utils_m), (
                f"makespan utilization outside [0,1]: max={max(utils_m)}"
            )
            result["driver_utilization_makespan"] = _summary_stats(utils_m)

    if "zone_imbalance" in metric_names:
        zone_counts: dict[int, int] = {}
        for o in delivered:
            zone_counts[o.destination_zone_id] = zone_counts.get(o.destination_zone_id, 0) + 1
        result["zone_imbalance"] = _gini(list(zone_counts.values()))

    summary_requested = [m for m in metric_names if m in _SUMMARY_METRICS]

    if "competitive_ratio" in metric_names:
        if offline_solver is None:
            result["competitive_ratio"] = _NAN
        else:
            offline = offline_solver.metrics(env, summary_requested, ainfo)
            result["competitive_ratio"] = {
                m: {
                    stat: result[m][stat] / offline[m][stat]
                    for stat in result[m]
                    if offline[m][stat] > 0
                }
                for m in summary_requested
                if m in result and m in offline
            }

    if "regret" in metric_names:
        if offline_solver is None:
            result["regret"] = _NAN
        else:
            result["regret"] = offline_solver.regret_curves(env, summary_requested)

    return result


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def busy_time_in_window(
    intervals: list[tuple[float, float]],
    window_start: float,
    window_end: float,
) -> float:
    """Measure of the union of `intervals` intersected with [window_start, window_end].

    Driver utilization is defined as the fraction of the measurement window during
    which a driver is not idle. Taking the *union* rather than the sum is what makes
    the result meaningful: the simulator can record the same wall-clock span more
    than once (for example a travel-to-restaurant span that abuts a delivery span),
    and summing those spans is what previously drove utilization above 1.

    Each interval is clipped to the window before merging, so the return value is
    always in [0, window_end - window_start].
    """
    if window_end <= window_start:
        return 0.0

    clipped = []
    for start, end in intervals:
        lo = max(start, window_start)
        hi = min(end, window_end)
        if hi > lo:
            clipped.append((lo, hi))

    if not clipped:
        return 0.0

    clipped.sort()
    total = 0.0
    cur_lo, cur_hi = clipped[0]
    for lo, hi in clipped[1:]:
        if lo > cur_hi:                 # disjoint: bank the run and start a new one
            total += cur_hi - cur_lo
            cur_lo, cur_hi = lo, hi
        elif hi > cur_hi:               # overlapping: extend the current run
            cur_hi = hi
    total += cur_hi - cur_lo
    return total


def _summary_stats(values: list[float]) -> dict[str, float]:
    """Returns avg, min, max, p90, p95, p99 for a list of floats."""
    if not values:
        return {"avg": _NAN, "min": _NAN, "max": _NAN, "p90": _NAN, "p95": _NAN, "p99": _NAN}
    return {
        "avg": statistics.mean(values),
        "min": min(values),
        "max": max(values),
        "p90": _percentile(values, 90),
        "p95": _percentile(values, 95),
        "p99": _percentile(values, 99),
    }


def _percentile(values: list[float], p: float) -> float:
    """Linear-interpolation percentile."""
    if not values:
        return _NAN
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    idx = (p / 100.0) * (n - 1)
    lo = int(idx)
    hi = min(lo + 1, n - 1)
    frac = idx - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def _gini(values: list[int | float]) -> float:
    """Gini coefficient of a list of non-negative values. Returns 0.0 for empty/zero-sum."""
    n = len(values)
    total = sum(values)
    if n == 0 or total == 0:
        return 0.0
    sorted_vals = sorted(values)
    weighted_sum = sum((i + 1) * v for i, v in enumerate(sorted_vals))
    return (2 * weighted_sum / (n * total)) - (n + 1) / n
