from abc import ABC, abstractmethod
from ..core.order import Order
from ..core.driver import Driver
from ..cost_functions.travel_time import AuxInfo
from ..core.environment import Environment


class OfflineSolver(ABC):

    @abstractmethod
    def metrics(self, env: Environment, metric_names: list[str], 
                ainfo: AuxInfo) -> dict[str, dict[str, float]]:
        """Optimal values for the given metrics: flow_time, travel_time, driver_util

        ainfo is related to the 
        
        {
            flow_time: {"min": 1.2, "avg": 2, "max": 3},
            travel_time: {"min": 1.2, "avg": 2, "max": 3},
            driver_util: {"min": 1.2, "avg": 2, "max": 3},
        }
        """
        order_stream: str | list[Order] = list(env.orders.values())
        ...

    @abstractmethod
    def regret_curves(
        self,
        env: Environment,
        metric_names: list[str],
    ) -> dict[str, list[tuple[float, float]]]:
        """Per-metric cumulative regret: 
        
        {
        flow_time: [(time, cumlative_regret), ...],
        ...
        }
        """
        warm_up_duration = env.warmup_duration
        post_warmup_batches = [
            (driver, batch) for driver, batch in env.batches
            if all(o.arrival_time >= warm_up_duration for o in batch)
            ]
        ...
