# Implementation Plan: Coverage-Aware Local Scoring (CALS) Dispatch Policy

## 0. Purpose and scope (read this first)

You are implementing **one** dispatch policy for an existing discrete-event
OFD (online food delivery) simulator. The policy is called **Coverage-Aware
Local Scoring (CALS)**.

This policy answers exactly one question: **when a driver becomes idle, which
restaurant-subqueue should it be assigned to?** It assigns the driver a
`(restaurant, destination_zone)` target. It does **NOT** decide when the driver
departs the restaurant once it arrives there (that is a separate
"departure-timing" rule, out of scope for this task — assume a fixed
depart-immediately or existing timing rule is already in place).

The policy works by scoring every eligible candidate assignment with a single
**cost function measured entirely in time units (seconds of expected order flow
time)**, then picking the candidate with the lowest cost. Keeping every term in
the same unit (seconds) is the core design principle — do not introduce terms in
other units (queue counts, distances in km, etc.) without converting them to
seconds first.

The simulator already exists. From the architecture, the relevant modules are:
- `policies/bundle_policy.py` — policy lives here, exposes a `tick()`-style entry point
- `cost/travel_time.py` — provides the travel-time / distance lookups
- `core/environment.py` — holds shared state
- state objects: `Driver`, `Order`, `Restaurant`, `Zone`

**Match the existing code's conventions.** This plan specifies the *math and
semantics* precisely; adapt naming/structure to the existing codebase rather
than creating a parallel design. Where this plan names a quantity, find the
existing field that already holds it before adding a new one.

---

## 1. The cost function (the whole policy in one equation)

When driver `ℓ` becomes idle in zone `A` at simulation time `t`, for each
candidate subqueue `(i, j)` (restaurant `i`, destination zone `j`) that has at
least one prepared order, compute:

```
C(i, j) =   travel
          + deliver_per_order
          - w_a * urgency
          + w_c * coverage
```

The driver is assigned to `argmin over (i,j) of C(i,j)`.
If no candidate exists, the driver stays idle.

Every one of the four terms below is in **seconds**. The two weights `w_a` and
`w_c` are the ONLY tunable parameters, and both have a one-sentence meaning.

---

## 2. The four terms, defined exactly

For a candidate `(i, j)`, first gather these primitives from simulator state:

| Symbol      | Meaning                                                              | Where it comes from |
|-------------|---------------------------------------------------------------------|---------------------|
| `A`         | zone the idle driver is currently in                                | `driver.zone` (its covered/home zone) |
| `z(i)`      | zone containing restaurant `i`                                      | `restaurant.zone` |
| `k`         | number of **prepared** orders waiting in subqueue `(i,j)`           | `len(restaurant.subqueue[j].prepared_orders)` |
| `a_ij`      | age of the **oldest** prepared order in subqueue `(i,j)`, in seconds| `t - min(order.arrival_time for order in that subqueue)` |
| `D[x, y]`   | interzone travel time from zone `x` to zone `y`, in seconds         | `cost/travel_time.py` lookup |
| `c(j)`      | intrazone routing coefficient for destination zone `j`             | `zone[j].c` (geometric property, precomputed) |
| `alpha`     | batching exponent, `0 < alpha < 1`, global constant                 | config / params |
| `n_z`       | number of drivers currently covering zone `z`                      | maintained coverage counter (see §4) |

Derived quantity used by several terms — the **batch service time**:

```
tau(i, j, k) = D[z(i), j] + c(j) * (k ** alpha)
```

This is the time for the driver to leave restaurant `i`, deliver all `k` orders
inside destination zone `j`, and finish. It is sublinear in `k` because
`alpha < 1`.

### Term 1 — `travel` (reposition cost)
```
travel = D[A, z(i)]
```
Time for the idle driver to drive from where it is now to the restaurant. Every
order in the eventual batch waits through this. Already in seconds.

### Term 2 — `deliver_per_order` (delivery cost, amortized over the batch)
```
deliver_per_order = tau(i, j, k) / k
```
The delivery trip serves `k` orders in one go, so the cost charged to a single
order is the per-order share. **This division by `k` is the entire batching
incentive**: because `tau` grows sublinearly, a bigger batch lowers per-order
cost. Do NOT add a separate "batching bonus" term — it is already here.

### Term 3 — `urgency` (aging penalty)
```
urgency = a_ij                     # age of oldest order, seconds
```
Used in the cost as `- w_a * urgency`. The **minus sign** makes older subqueues
*cheaper* (more attractive), pulling drivers toward orders that have already
waited a long time. This is what protects tail (worst-case) flow time.

### Term 4 — `coverage` ("no zone left behind", converted to seconds)
This is the only quantity not naturally in seconds, so we convert it by
multiplying by `tau` (the duration over which the coverage change persists).

Two effects of taking this assignment:
```
leaving_penalty  = tau(i, j, k)   if  n_A == 1   else 0
                   # ℓ is the LAST driver covering A, so leaving uncovers A
                   # for the whole trip duration -> a cost

relieving_bonus  = tau(i, j, k)   if  n_j == 0   else 0
                   # j is currently uncovered, so arriving there relieves it
                   # -> a credit

coverage = leaving_penalty - relieving_bonus
```
Used in the cost as `+ w_c * coverage`. Positive when the assignment strands a
zone (bad); negative when it rescues an uncovered zone (good).

---

## 3. The two weights (the only knobs)

```
w_a  >= 0   "urgency weight":  how many seconds of cost is one second of an
                               order's age worth?
                               w_a = 0 -> ignore aging.
                               w_a = 1 -> age trades one-for-one with travel.
                               w_a > 1 -> tail-averse (detour to rescue old orders).

w_c  >= 0   "coverage weight": how many seconds of flow time is it worth
                               spending to avoid leaving a zone uncovered for
                               one second?
                               w_c = 0 -> coverage OFF, pure local optimization.
                               w_c large -> coverage dominates.
```

Both default to `0`, which recovers a plain nearest-batch greedy policy.
Expose both as constructor/config parameters. Do not hardcode them.

---

## 4. Coverage counter `n_z` — the one piece of shared state to maintain

`n_z` = number of drivers whose **covered zone** is `z`.

A driver's "covered zone" is:
- the zone it is idle in, if idle; or
- the destination zone of its current delivery, if busy.

Maintain an integer array/dict `n[z]` for all zones, updated **incrementally**
(O(1) per event), NOT recomputed by scanning all drivers each decision:

- **Initialization:** when drivers are placed at simulation start, increment
  `n[driver.zone]` for each.
- **On assignment** (inside the policy, after choosing `(i*, j*)` for driver in
  zone `A`):
  ```
  n[A]  -= 1          # driver leaves its current covered zone
  n[j*] += 1          # driver now covers its destination zone
  driver.covered_zone = j*
  ```
  This update happens **immediately at assignment time**, not at delivery
  completion. This is deliberate (see §6, "coordination for free").

- Sanity invariant to assert in tests: `sum(n[z] for all z) == number_of_drivers`
  at all times.

> If the simulator already tracks something equivalent to a driver's
> home/covered zone, reuse it. Only add `n[z]` if no equivalent live counter
> exists.

---

## 5. The algorithm (reference pseudocode)

```
FUNCTION assign_idle_driver(driver L, time t):
    A = L.covered_zone
    best_cost = +infinity
    choice    = None

    FOR each restaurant i:
        FOR each destination zone j such that subqueue (i, j) has >= 1 prepared order:
            k   = number of prepared orders in subqueue (i, j)
            if k == 0: continue

            a_ij = t - (arrival_time of oldest prepared order in subqueue (i,j))

            tau  = D[zone_of(i), j] + c(j) * (k ** alpha)

            travel            = D[A, zone_of(i)]
            deliver_per_order = tau / k
            urgency           = a_ij
            leaving_penalty   = tau if n[A] == 1 else 0.0
            relieving_bonus   = tau if n[j] == 0 else 0.0
            coverage          = leaving_penalty - relieving_bonus

            C = travel + deliver_per_order - w_a * urgency + w_c * coverage

            if C < best_cost:
                best_cost = C
                choice    = (i, j)

    IF choice is None:
        leave L idle in zone A
        RETURN

    (i_star, j_star) = choice
    assign L to restaurant i_star, target destination subqueue j_star
    # update coverage immediately:
    n[A]      -= 1
    n[j_star] += 1
    L.covered_zone = j_star
    RETURN choice
```

### Tie-breaking
If two candidates have equal `C` (within a small epsilon, e.g. `1e-9`), break
ties deterministically — recommended order: (1) larger `k` (bigger batch),
then (2) smaller `travel`, then (3) lowest `(restaurant_id, zone_id)`. A
deterministic rule is required so runs are reproducible across seeds.

---

## 6. Why the immediate `n[]` update matters (do not skip it)

When several drivers go idle at nearly the same simulated instant, they are
scored one at a time. Because `n[A]`/`n[j]` are updated the moment a driver is
assigned (line `n[j_star] += 1`), the **next** driver scored in that same
instant already sees the zone as covered and will not pile onto it.

This is what gives the policy its "coordinated, no-zone-left-behind" behavior
**without** solving a joint matching problem. It is a sequential-greedy
coordination. Implement the update exactly where shown. If you instead deferred
the coverage update to delivery-completion time, multiple drivers could all rush
to cover the same empty zone — the bug this design specifically avoids.

---

## 7. Integration checklist (wire-up)

1. **Locate the policy interface.** Find how existing policies are invoked
   (architecture shows `policies/bundle_policy.py` and a `policy.tick()` /
   per-driver assignment hook). Implement CALS behind the same interface so it
   is selectable by name/config alongside existing policies.

2. **Travel times.** Use the existing `cost/travel_time.py` for `D[x, y]`. Do
   NOT recompute distances. Confirm whether it returns interzone time directly
   (centroid-to-centroid Manhattan distance scaled to time units, per the paper)
   and use that. If it is keyed by zone IDs, pass `zone_of(i)` and `j`.

3. **Subqueue access.** Confirm how prepared orders are stored per
   `(restaurant, destination_zone)`. Only **prepared** orders count toward `k`
   and toward `a_ij`; orders still in preparation are not yet eligible and must
   be excluded.

4. **Oldest-order age `a_ij`.** If the subqueue does not already track its oldest
   prepared order's arrival time, add a cheap accessor (a min over the subqueue,
   or maintain the front of a FIFO ordered by arrival time). This is the one new
   read the policy needs.

5. **Coverage counter `n[z]`.** Add as described in §4 if not already present.
   Initialize at driver placement; update on assignment.

6. **Parameters `w_a`, `w_c`, `alpha`.** Read from config. `alpha` should already
   exist (used by the batch service time elsewhere); reuse the same value, do not
   redefine it.

7. **Eligibility filter.** A candidate `(i, j)` is eligible iff it has
   `k >= 1` prepared orders. Skip empty subqueues entirely (do not score them).

---

## 8. Tests to write (acceptance criteria)

Write these as unit tests against the policy in isolation (mock the state) plus
one integration smoke test.

**Unit — term correctness**
- `T1` With `w_a = 0, w_c = 0`: the chosen candidate is exactly the one
  minimizing `D[A, z(i)] + tau/k`. (Pure greedy baseline recovered.)
- `T2` Batching reward: holding everything else equal, a subqueue with larger
  `k` yields a lower `deliver_per_order`. Construct two candidates identical
  except `k = 1` vs `k = 4` and assert the `k = 4` one has lower cost (with
  `alpha = 0.5`).
- `T3` Urgency: with `w_a > 0`, raising `a_ij` of one candidate strictly lowers
  its cost; large enough `a_ij` makes it win over a closer, fresher candidate.
- `T4` Coverage leave-penalty: set `n[A] = 1` (driver is last in `A`); assert the
  candidate's cost increases by exactly `w_c * tau` relative to the `n[A] = 2`
  case, all else equal.
- `T5` Coverage relieve-bonus: set `n[j] = 0`; assert cost decreases by exactly
  `w_c * tau` relative to the `n[j] = 1` case, all else equal.
- `T6` No double effect: when `n[A] = 1` AND `n[j] = 0` simultaneously, coverage
  term = `w_c * (tau - tau) = 0`. Assert it nets to zero.

**Unit — selection & bookkeeping**
- `T7` No eligible candidate -> driver left idle, returns None, `n[]` unchanged.
- `T8` After assignment, `n[A]` decreased by 1 and `n[j_star]` increased by 1,
  and `driver.covered_zone == j_star`.
- `T9` Deterministic tie-break: two exactly-equal-cost candidates resolve per the
  rule in §5, identically across repeated runs.

**Invariant**
- `T10` At every event in a short simulation, `sum(n) == num_drivers`.

**Integration smoke**
- `T11` Run a short simulation (small `Z`, `R`, `N`, short horizon) end-to-end
  with CALS as the policy; assert it completes, produces finite flow times, and
  that increasing `w_c` from 0 reduces the across-zone variance of driver-idle
  time (the spatial-imbalance diagnostic) — i.e. coverage actually spreads the
  fleet. This is a directional check, not an exact value.

---

## 9. Things to deliberately NOT do

- **Do NOT** add a separate "batching lookahead" or "expected future orders"
  term to this score. Batching is already rewarded by `tau / k`. Anticipatory
  waiting belongs to the separate departure-timing rule, not to this
  assignment policy. Mixing them is the main pitfall.
- **Do NOT** mix units. If you find yourself adding a raw count or a raw
  distance-in-km to the score, convert it to seconds first or leave it out.
- **Do NOT** recompute `n[z]` by scanning all drivers each decision; maintain it
  incrementally.
- **Do NOT** count unprepared orders in `k` or `a_ij`.
- **Do NOT** solve a matching / assignment-problem optimization here. CALS is
  intentionally a per-driver scan with immediate coverage update (§6). A joint
  matching version is a *different* policy and out of scope.

---

## 10. One-paragraph summary for the implementer

When a driver goes idle, look at every restaurant-destination subqueue that has
at least one prepared order. For each, compute a single cost in seconds: the time
to drive to the restaurant, plus the delivery time divided by how many orders
you'd carry (this rewards big batches), minus a weight `w_a` times how long the
oldest order there has already waited (this rescues stale orders), plus a weight
`w_c` times a coverage term that charges you for stranding the last driver out of
a zone and credits you for filling an empty zone (this keeps the fleet spread —
"no zone left behind"). Send the driver to the lowest-cost option, and
immediately update the per-zone driver counts so the next idle driver scored in
the same instant won't duplicate the choice. Two knobs only: `w_a`, `w_c`, both
zero by default.
