from mvp_sim.simulator.events import *
from mvp_sim.simulator.event_handler import EventHandler
from mvp_sim.core.environment import Environment
from ..base import Policy


class AJRP(Policy):
    """
    Approximate Joint dispatching and Routing Policy (AJRP).

    Based on:
        Liu, S., & Luo, Z. (2022).
        "On-Demand Delivery from Stores: Dynamic Dispatching and Routing
        with Random Demand."
        arXiv:2107.13058  https://arxiv.org/abs/2107.13058

    Paper summary:
        AJRP approximates a finite-horizon stochastic DP (JDR) by replacing
        the intractable cost-to-go with a sum of single-period myopic costs.
        At each dispatch wave the operator solves a joint dispatching (how
        many drivers) and routing (which orders) MILP that minimises current
        delivery cost plus anticipated future cost, subject to driver
        availability constraints across all remaining waves.

    Adaptations for this simulator:

        1. No historical data. E_cost[wave_idx][k] — the expected delivery
           cost at wave wave_idx with k drivers — is estimated online via a
           running mean of observed single-wave costs. All entries start at
           0.0 and improve as waves complete during the simulation.

        2. Multi-restaurant, single-zone trips. The paper has one depot and
           multi-stop routes. Here each driver trip serves one (restaurant,
           zone) pair. Feasible dispatch options are all such pairs that have
           ready orders, crossed with the set of idle drivers.

        3. The MILP is solved by enumerating k ∈ {0, …, max_k} (number of
           drivers to dispatch). For each k the assignment is found greedily
           (min-cost, each driver and each (rest, zone) pair used at most
           once). This is effectively exact when the number of idle drivers
           and (rest, zone) options is small, which is typical in practice.

        4. Wave clock. Periodic PolicyWaitEvents drive the primary dispatch
           cadence. DriverReadyEvent and OrderReadyEvent trigger opportunistic
           dispatches so idle drivers do not sit idle for a full interval.
           Duplicate execution at the same timestamp is suppressed via
           _last_wave_time.

    MILP formulation (Section 3–4 of the paper, adapted):

        Sets:
            D       — idle drivers at current wave t_n
            P       — (rest r, zone z) pairs with ready orders
            O(r,z)  — ready orders at rest r destined for zone z
            n'      — future wave indices {n+1, …, N}
            k       — possible dispatch count {0, …, K̄}

        Variables:
            b_{d,(r,z)} ∈ {0,1}   dispatch driver d to (r,z) now
            x_{n',k}    ∈ {0,1}   dispatch exactly k drivers at future wave n'

        Objective:
            min  Σ c_{d,(r,z)}·b  +  Σ_{n'} Σ_k E_cost[n'][k]·x_{n',k}

        Constraints:
            (1) Σ_{(r,z)} b_{d,(r,z)} ≤ 1          each driver at most once
            (2) Σ_d b_{d,(r,z)} ≤ 1                 each (r,z) at most once
            (3) Σ_k x_{n',k} = 1                    one-hot per future wave
            (4) ζ_{n'} + Σ b·1[trip > t_{n'}−t_n] + Σ_k k·x_{n',k} ≤ K̄
                                                     driver availability

        Here constraint (4) is the anticipatory coupling: dispatching more
        drivers now tightens the availability bound for future waves, forcing
        higher anticipated future costs into the objective and causing the
        policy to hold back drivers when future demand is expected to be heavy.

        The MILP decouples over k: for fixed current dispatch assignments the
        x subproblem separates per wave, each solved by picking the k that
        minimises E_cost[n'][k] subject to the availability bound.

    Parameters:
        wave_interval (float): dispatch period Δ (length of each wave).
    """

    _EPS: float = 1e-9

    def __init__(self, wave_interval: float):
        self.wave_interval = wave_interval
        self._wave_scheduled: bool = False
        self._last_wave_time: float = -float('inf')
        # _e_cost[wave_idx][k]       running mean observed delivery cost
        # _e_cost_counts[wave_idx][k] number of observations
        self._e_cost: dict[int, dict[int, float]] = {}
        self._e_cost_counts: dict[int, dict[int, int]] = {}

    # ------------------------------------------------------------------
    # Online E_cost table
    # ------------------------------------------------------------------

    def _wave_index(self, time: float) -> int:
        return int(time / self.wave_interval)

    def _update_e_cost(self, wave_idx: int, k: int, cost: float) -> None:
        self._e_cost.setdefault(wave_idx, {})
        self._e_cost_counts.setdefault(wave_idx, {})
        n = self._e_cost_counts[wave_idx].get(k, 0)
        old = self._e_cost[wave_idx].get(k, 0.0)
        self._e_cost[wave_idx][k] = (old * n + cost) / (n + 1)
        self._e_cost_counts[wave_idx][k] = n + 1

    def _get_e_cost(self, wave_idx: int, k: int) -> float:
        return self._e_cost.get(wave_idx, {}).get(k, 0.0)

    # ------------------------------------------------------------------
    # Wave scheduling
    # ------------------------------------------------------------------

    def _schedule_next_wave(self, time: float, env: Environment, eh: EventHandler) -> None:
        """Push the next periodic PolicyWaitEvent if none is already queued."""
        if self._wave_scheduled:
            return
        next_t = time + self.wave_interval
        if next_t > env.horizon:
            return
        placeholder = next(iter(env.drivers.values()))
        eh.push_event(PolicyWaitEvent(time=next_t, driver=placeholder))
        self._wave_scheduled = True

    # ------------------------------------------------------------------
    # Dispatch helpers
    # ------------------------------------------------------------------

    def _collect_pairs(self, env: Environment) -> list[tuple]:
        """
        Enumerate all feasible (driver, rest, zone_id, orders, total_cost, trip_dur) options.

        total_cost  — sum of cumulative delivery costs across all orders in the batch,
                      used as c_{d,(r,z)} in the MILP objective.
        trip_dur    — last element of orders_cost, a proxy for when the driver
                      returns to base (used in constraint (4)).
        """
        result = []
        for driver in env.idle_drivers():
            for rest in env.restaurants.values():
                for zone_id, oids in rest.ready_subqueues.items():
                    if not oids:
                        continue
                    orders = [env.orders[oid] for oid in oids]
                    costs = env.compute_orders_travel_cost(orders, driver)
                    if not costs:
                        continue
                    result.append((driver, rest, zone_id, orders, sum(costs), costs[-1]))
        return result

    def _greedy_assign(self, pairs: list[tuple], k: int) -> list[tuple]:
        """
        Greedy min-cost assignment of k driver → (rest, zone) pairs.

        Sorts all options by total_cost and greedily picks non-conflicting
        entries (each driver and each (rest, zone) used at most once).
        Returns fewer than k entries only if not enough valid pairs exist.
        """
        used_drivers: set[int] = set()
        used_rz: set[tuple] = set()
        result = []
        for entry in sorted(pairs, key=lambda p: p[4]):
            if len(result) == k:
                break
            d, r, z = entry[0], entry[1], entry[2]
            if d.driver_id in used_drivers or (r.restaurant_id, z) in used_rz:
                continue
            result.append(entry)
            used_drivers.add(d.driver_id)
            used_rz.add((r.restaurant_id, z))
        return result

    def _future_cost(
        self,
        assignments: list[tuple],
        time: float,
        wave_idx: int,
        env: Environment,
    ) -> float:
        """
        Compute anticipated future delivery cost for a given current dispatch.

        Implements constraint (4): for each future wave n', the available
        driver count is K̄ minus already-en-route drivers (ζ_{n'}) minus
        drivers dispatched NOW still on their trip at n'. The best achievable
        future cost is min_{k ≤ avail} E_cost[n'][k], summed over all
        remaining waves.
        """
        K_bar = len(env.drivers)
        n_future = int((env.horizon - time) / self.wave_interval)
        total = 0.0

        for offset in range(1, n_future + 1):
            t_f = time + offset * self.wave_interval
            fwi = wave_idx + offset

            # ζ_{n'}: drivers already en-route before this wave
            zeta = sum(
                1 for d in env.drivers.values()
                if not d.is_idle() and d.next_available_time > t_f
            )
            # drivers dispatched now still on their trip at t_f
            still_out = sum(
                1 for *_, trip_dur in assignments
                if time + trip_dur > t_f
            )

            avail = max(0, K_bar - zeta - still_out)
            best_fc = min(
                (self._get_e_cost(fwi, k) for k in range(avail + 1)),
                default=0.0,
            )
            total += best_fc

        return total

    # ------------------------------------------------------------------
    # Core dispatch logic
    # ------------------------------------------------------------------

    def _dispatch_now(self, time: float, env: Environment, eh: EventHandler) -> None:
        """
        Joint dispatch decision: enumerate k ∈ {0, …, max_k} and execute
        the assignment that minimises current delivery cost + future cost.

        Updates the online E_cost table after each dispatch wave.
        """
        if abs(time - self._last_wave_time) < self._EPS:
            return
        self._last_wave_time = time

        idle = env.idle_drivers()
        pairs = self._collect_pairs(env)

        if not idle or not pairs:
            if not self._wave_scheduled:
                self._schedule_next_wave(time, env, eh)
            return

        n_options = len({(r.restaurant_id, z) for _, r, z, *_ in pairs})
        max_k = min(len(idle), n_options)
        wave_idx = self._wave_index(time)

        best_total = float('inf')
        best_assignments: list[tuple] = []

        for k in range(max_k + 1):
            assignments = self._greedy_assign(pairs, k) if k > 0 else []
            if k > 0 and len(assignments) < k:
                continue
            total = (
                sum(a[4] for a in assignments)
                + self._future_cost(assignments, time, wave_idx, env)
            )
            if total < best_total:
                best_total = total
                best_assignments = assignments

        self._update_e_cost(
            wave_idx,
            len(best_assignments),
            sum(a[4] for a in best_assignments),
        )

        for driver, rest, zone_id, orders, *_ in best_assignments:
            eh.handle_event(OrdersAssignEvent(time, orders, rest, driver))

        if not self._wave_scheduled:
            self._schedule_next_wave(time, env, eh)

    def _handle_policy_wait(self, time: float, env: Environment, eh: EventHandler) -> None:
        """Scheduled wave: reset flag, dispatch, reschedule."""
        self._wave_scheduled = False
        self._dispatch_now(time, env, eh)
        self._schedule_next_wave(time, env, eh)

    # ------------------------------------------------------------------
    # tick
    # ------------------------------------------------------------------

    def tick(self, event: Event, environment: Environment, event_handler: EventHandler) -> None:
        if isinstance(event, OrderArriveEvent):
            return
        elif isinstance(event, OrderReadyEvent):
            if environment.idle_drivers():
                self._dispatch_now(event.time, environment, event_handler)
        elif isinstance(event, (OrdersAssignEvent, OrderDeliveredEvent,
                                DriverArriveEvent, DriverRepositionAssignEvent)):
            return
        elif isinstance(event, (DriverReadyEvent, DriverRepositionArriveEvent)):
            self._dispatch_now(event.time, environment, event_handler)
        elif isinstance(event, PolicyWaitEvent):
            self._handle_policy_wait(event.time, environment, event_handler)
        else:
            raise TypeError(f"Unhandled event: {type(event)}")
