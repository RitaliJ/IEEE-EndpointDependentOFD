import math
from mvp_sim.core.order import Order
from mvp_sim.core.driver import Driver
from dataclasses import dataclass
from abc import ABC, abstractmethod
from mvp_sim.dist_functions.bank import (
    euclidean_dist_zone,
    manhattan_dist,
)
from typing import Optional

# THIS FILE THAT TAKES IN A BATCH OF ORDERS AND A DRIVER, AND CALCULATES THE 
# TRAVEL TIME COST OF THAT BATCH OF ORDERS FOR THAT DRIVER DISTANCE is in units 
# of time. 

# ============ Helpers =============


def floyd_warshall(graph):
    n = len(graph)

    dist = [row[:] for row in graph]

    nxt: list[list[Optional[int]]] = [[None] * n for _ in range(n)]

    for i in range(n):
        for j in range(n):
            if graph[i][j] != math.inf and i != j:
                nxt[i][j] = j

    for k in range(n):
        for i in range(n):
            for j in range(n):

                if dist[i][k] == math.inf or dist[k][j] == math.inf:
                    continue

                new_dist = dist[i][k] + dist[k][j]

                if new_dist < dist[i][j]:
                    dist[i][j] = new_dist
                    nxt[i][j] = nxt[i][k]

    return dist, nxt

def get_path(nxt, u, v):
    if nxt[u][v] is None:
        return []

    path = [u]

    while u != v:
        u = nxt[u][v]
        path.append(u)

    return path

@dataclass
class AuxInfo:
    c_matrix : list[list[float]] | None
    alpha : float | None
    zone_area: float | None
    graph: dict[int, int] | None
    # Parameters of the sublinear batch-service model from the paper,
    #     tau(i, j, k) = D[z(i), j] + c(j) * k**batch_alpha,   0 < batch_alpha < 1.
    # `batch_alpha` is the paper's alpha (the exponent). `zone_scale` is c(j), keyed
    # by 1-based destination zone id and already expressed in time units.
    # NOTE: the legacy `alpha` field above is the BHH constant (a scale, not an
    # exponent) used by the star/poisson experiments; the two are different
    # quantities and must not be conflated.
    batch_alpha: float | None = None
    zone_scale: dict[int, float] | None = None


class TravelCost(ABC):
    @staticmethod
    @abstractmethod
    def orders_cost(orders: list[Order], driver: Driver, ainfo: AuxInfo) -> list[float]:
        pass

    @staticmethod
    @abstractmethod
    def driver_cost(driver: Driver, ainfo: AuxInfo) -> float:
        pass

    @staticmethod
    def service_time(current_zone_id: int, dest_zone_id: int, k: int, ainfo: AuxInfo) -> float:
        """tau(i, j, k): total service time for a zone-homogeneous batch of k orders.

        This is the single definition of batch service cost. A policy that scores
        candidate batches must call this rather than reimplement the formula --
        otherwise the policy optimises a different objective than the simulator
        charges it for, and the comparison measures the mismatch instead of the
        policy. `orders_cost` is defined in terms of this method for the same
        reason.

        Zone ids are 1-based, matching Order.destination_zone_id.
        """
        raise NotImplementedError(
            f"{__class__.__name__} does not define a batch service time"
        )


class sublinear_intrazone(TravelCost):
    @staticmethod
    def orders_cost(orders: list[Order], driver: Driver, ainfo: AuxInfo) -> list[float]:
        """Sublinear batch service time, per the paper's model

            tau(i, j, k) = D[z(i), j] + c(j) * k**alpha,   0 < alpha < 1.

        D[z(i), j] is the interzone transit from the driver's current zone to the
        batch's destination zone; c(j) * k**alpha approximates the within-zone work
        of serving k nearby destinations. Marginal cost per stop is increasing but
        diminishing, so consolidating compatible orders is rewarded.

        Assumptions:
            every order in the batch shares one destination zone (guaranteed by the
            zone-subqueue batching rule -- a policy takes all ready orders in Q_ij).

        Parameters are read from `ainfo`:
            c_matrix:    zone-to-zone travel cost matrix
            zone_scale:  c(j), per 1-based destination zone id, in time units
            batch_alpha: the exponent alpha

        Falls back to the legacy BHH parameterisation (`alpha` as the BHH constant
        with a fixed square-root exponent) when the explicit fields are absent, so
        the star/poisson experiments keep their previous behaviour:
            alpha * sqrt(k * zone_area) == (alpha * sqrt(zone_area)) * k**0.5.

        Returns:
            list[float]: cumulative cost per order; cost[i] is the estimated
                         total travel time after delivering the first i+1 orders
        """
        c_matrix = ainfo.c_matrix
        assert c_matrix

        if not orders:
            return []

        current_zone = driver.curr_zone_id - 1
        dest_zone_id = orders[0].destination_zone_id
        dest_zone = dest_zone_id - 1
        if current_zone >= len(c_matrix) or dest_zone >= len(c_matrix[current_zone]):
                raise KeyError(
                    f"No travel cost entry for ({current_zone!r}, {dest_zone!r})"
                )
        if any(o.destination_zone_id != dest_zone_id for o in orders):
            raise ValueError(
                "sublinear_intrazone requires a zone-homogeneous batch; got "
                f"destinations {sorted({o.destination_zone_id for o in orders})}"
            )

        return [
            sublinear_intrazone.service_time(driver.curr_zone_id, dest_zone_id, i + 1, ainfo)
            for i in range(len(orders))
        ]

    @staticmethod
    def service_time(current_zone_id: int, dest_zone_id: int, k: int, ainfo: AuxInfo) -> float:
        """tau(i, j, k) = D[z(i), j] + c(j) * k**alpha. See TravelCost.service_time."""
        c_matrix = ainfo.c_matrix
        assert c_matrix
        current_zone, dest_zone = current_zone_id - 1, dest_zone_id - 1
        if current_zone >= len(c_matrix) or dest_zone >= len(c_matrix[current_zone]):
            raise KeyError(f"No travel cost entry for ({current_zone!r}, {dest_zone!r})")

        if ainfo.zone_scale is not None and ainfo.batch_alpha is not None:
            if dest_zone_id not in ainfo.zone_scale:
                raise KeyError(f"No zone_scale c(j) entry for destination zone {dest_zone_id!r}")
            c_j = ainfo.zone_scale[dest_zone_id]
            batch_alpha = ainfo.batch_alpha
        else:
            assert ainfo.alpha, "sublinear_intrazone needs zone_scale/batch_alpha or legacy alpha"
            assert ainfo.zone_area, "sublinear_intrazone needs zone_scale/batch_alpha or legacy zone_area"
            c_j = ainfo.alpha * math.sqrt(ainfo.zone_area)
            batch_alpha = 0.5

        return c_matrix[current_zone][dest_zone] + c_j * (k ** batch_alpha)

    @staticmethod
    def driver_cost(driver: Driver, ainfo: AuxInfo) -> float:
        c_matrix = ainfo.c_matrix
        assert c_matrix
        curr_zone = driver.curr_zone_id - 1
        dest_zone = driver.dest_zone_id
        assert dest_zone
        dest_zone -= 1
        if curr_zone == dest_zone:
             if driver.curr_pt == driver.dest_pt:
                  return 0.0
        if curr_zone >= len(c_matrix) or dest_zone >= len(c_matrix[curr_zone]):
                raise KeyError(
                    f"No travel cost entry for ({curr_zone!r}, {dest_zone!r})"
                )
        return c_matrix[curr_zone][dest_zone]
        

class zone_fixed_cost_matrix(TravelCost):
    @staticmethod
    def orders_cost(orders: list[Order], driver: Driver, ainfo: AuxInfo) -> list[float]:
        """
        Given a square matrix, it outputs the travel cost of that batch of orders
        (the policy should be taking care of how to properly batch and optimize
        orders)

        Args:
            tuple[list[Order], Driver]: represents the list of orders
                                        that the driver was assigned

        Returns:
            list[float]: cumulative travel cost per order; cost[i] is the total
                         travel time from the driver's start through order i's delivery

        Raises KeyError if the order's src, dest zones are not in cost_matrix.
        """
        c_matrix = ainfo.c_matrix
        assert c_matrix
        costs = []
        cumulative = 0.0
        current_zone = driver.curr_zone_id - 1

        for order in orders:
            dest_zone = order.destination_zone_id - 1
            if current_zone >= len(c_matrix) or dest_zone >= len(c_matrix[current_zone]):
                raise KeyError(
                    f"No travel cost entry for ({current_zone!r}, {dest_zone!r})"
                )
            cumulative += c_matrix[current_zone][dest_zone]
            costs.append(cumulative)
            current_zone = dest_zone

        return costs

    @staticmethod
    def service_time(current_zone_id: int, dest_zone_id: int, k: int, ainfo: AuxInfo) -> float:
        """Linear batch cost: the first stop pays transit, each further stop pays the
        matrix diagonal. See TravelCost.service_time."""
        c_matrix = ainfo.c_matrix
        assert c_matrix
        current_zone, dest_zone = current_zone_id - 1, dest_zone_id - 1
        if current_zone >= len(c_matrix) or dest_zone >= len(c_matrix[current_zone]):
            raise KeyError(f"No travel cost entry for ({current_zone!r}, {dest_zone!r})")
        return c_matrix[current_zone][dest_zone] + (k - 1) * c_matrix[dest_zone][dest_zone]

    @staticmethod
    def driver_cost(driver: Driver, ainfo: AuxInfo) -> float:
        c_matrix = ainfo.c_matrix
        assert c_matrix
        curr_zone = driver.curr_zone_id - 1
        dest_zone = driver.dest_zone_id
        assert dest_zone
        dest_zone -= 1
        if curr_zone == dest_zone:
             if driver.curr_pt == driver.dest_pt:
                  return 0.0
        if curr_zone >= len(c_matrix) or dest_zone >= len(c_matrix[curr_zone]):
                raise KeyError(
                    f"No travel cost entry for ({curr_zone!r}, {dest_zone!r})"
                )
        return c_matrix[curr_zone][dest_zone]

class star_graph_cost(TravelCost):
    @staticmethod
    def orders_cost(orders: list[Order], driver: Driver, ainfo: AuxInfo) -> list[float]:
        star_graph = ainfo.graph
        assert star_graph
        costs: list[float] = []
        cumulative = 0.0
        current_pt = driver.curr_pt
        current_zone = driver.curr_zone_id

        for order in orders:
            dest_zone = order.destination_zone_id
            if current_zone not in star_graph or dest_zone not in star_graph:
                raise KeyError(
                    f"No travel cost entry for {current_zone!r} or {dest_zone!r}"
                )
            if current_pt != order.destination:
                cumulative += star_graph[current_zone] + star_graph[dest_zone]
            costs.append(cumulative)
            current_pt = order.destination
            current_zone = dest_zone

        return costs

    @staticmethod
    def driver_cost(driver: Driver, ainfo: AuxInfo) -> float:
        star_graph = ainfo.graph
        assert star_graph
        if driver.curr_pt == driver.dest_pt:
            return 0.0
        assert driver.dest_zone_id
        return star_graph[driver.curr_zone_id] + star_graph[driver.dest_zone_id]
             

class euclidean(TravelCost):
    @staticmethod
    def orders_cost(orders: list[Order], driver: Driver, ainfo: AuxInfo) -> list[float]:
        costs = []
        cumulative = 0.0
        current_pos = driver.curr_pt

        for order in orders:
            cumulative += euclidean_dist_zone(current_pos, order.destination)
            costs.append(cumulative)
            current_pos = order.destination

        return costs

    @staticmethod
    def driver_cost(driver: Driver, ainfo: AuxInfo) -> float:
        assert driver.dest_pt
        return euclidean_dist_zone(driver.curr_pt, driver.dest_pt)

class manhattan(TravelCost):
    @staticmethod
    def orders_cost(orders: list[Order], driver: Driver, ainfo: AuxInfo) -> list[float]:
        costs = []
        cumulative = 0.0
        current_pos = driver.curr_pt

        for order in orders:
            cumulative += manhattan_dist(current_pos, order.destination)
            costs.append(cumulative)
            current_pos = order.destination

        return costs

    @staticmethod
    def driver_cost(driver: Driver, ainfo: AuxInfo) -> float:
        assert driver.dest_pt
        return manhattan_dist(driver.curr_pt, driver.dest_pt)
