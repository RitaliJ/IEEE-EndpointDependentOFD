_ALL_METRICS = {
    "total_orders",
    "undelivered_orders",
    # Explicit completion accounting for the measurement window. `arrived_orders`
    # counts every order that arrived in [warmup, horizon]; delivered + undelivered
    # partition it exactly, so flow-time comparisons can be checked for censoring.
    "arrived_orders",
    "delivered_orders",
    "completion_rate",
    "flow_time",
    "travel_time",
    "avg_batch_size",
    "batch_efficiency",
    "driver_utilization",
    # Utilization measured over [warmup, makespan] instead of [warmup, horizon].
    # `horizon` is the last *arrival*, so in an overloaded city the fleet is still
    # working long after it and driver_utilization saturates at 1.0 for every
    # policy, which makes it useless for comparison. The makespan variant covers
    # the period the fleet is actually serving and stays informative.
    "driver_utilization_makespan",
    "makespan",
    "zone_imbalance",
    "competitive_ratio",
    "regret",
}

# metrics that produce summary_stats dicts (avg/min/max/p90/p95/p99)
# competitive_ratio and regret are computed over these
_SUMMARY_METRICS = {"flow_time", "travel_time", "driver_utilization",
                    "driver_utilization_makespan"}
