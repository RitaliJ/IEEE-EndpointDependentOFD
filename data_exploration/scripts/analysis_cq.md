# Delivery CQ — Exploratory Analysis


## 1. Load & Basic Overview

**Shape:** 931,351 rows × 17 columns

**Columns:** ['order_id', 'region_id', 'city', 'courier_id', 'lng', 'lat', 'aoi_id', 'aoi_type', 'accept_time', 'accept_gps_time', 'accept_gps_lng', 'accept_gps_lat', 'delivery_time', 'delivery_gps_time', 'delivery_gps_lng', 'delivery_gps_lat', 'ds']

| Column | Unique | Nulls |
| --- | --- | --- |
| `order_id` | 931,351 | 0 |
| `region_id` | 48 | 0 |
| `city` | 1 | 0 |
| `courier_id` | 1,494 | 0 |
| `lng` | 82,330 | 0 |
| `lat` | 77,680 | 0 |
| `aoi_id` | 17,451 | 0 |
| `aoi_type` | 16 | 0 |
| `accept_time` | 92,881 | 0 |
| `accept_gps_time` | 92,881 | 0 |
| `accept_gps_lng` | 221 | 0 |
| `accept_gps_lat` | 222 | 0 |
| `delivery_time` | 150,039 | 0 |
| `delivery_gps_time` | 150,039 | 0 |
| `delivery_gps_lng` | 13,821 | 0 |
| `delivery_gps_lat` | 11,426 | 0 |
| `ds` | 184 | 0 |

## 2. Data Quality

- Timestamp parse errors: **0**
- Cross-midnight deliveries corrected: **3**
- Still-negative durations (data errors): **3**

**Delivery duration distribution (minutes):**

| Percentile | Minutes | Hours |
| --- | --- | --- |
| min | -421417.0 | -7023.6 |
| p5 | 29.0 | 0.5 |
| p25 | 83.0 | 1.4 |
| p50 | 151.0 | 2.5 |
| p75 | 256.0 | 4.3 |
| p95 | 745.0 | 12.4 |
| max | 128630.0 | 2143.8 |

- Deliveries < 10 min (likely errors): **19,801**
- Deliveries > 8 h (multi-day/outliers): **95,139**
- Deliveries > 24 h: **31,231**

**Pickup → driver-at-accept distance (km, sample n=10,000):** median=2.44  p95=6.48  max=180.42
**Pickup → delivery distance (km, sample n=10,000):** median=0.07  p95=1.46  max=11594.39

## 3. Column Mapping to Simulator Model

| CSV Column | Simulator Field |
| --- | --- |
| `courier_id` | `Driver.driver_id` |
| `region_id` | `Zone.zone_id` (48 unique regions) |
| `aoi_id` | `Restaurant.restaurant_id` (pickup point) |
| `aoi_type` | type of pickup point |
| `lng` / `lat` | `Restaurant.location` / `Order.source_location` |
| `accept_gps_lng/lat` | `Driver.location` at time of assignment |
| `delivery_gps_lng/lat` | `Order.destination_location` |
| `accept_time` | `Order.arrival_time` (no separate prep_time) |
| `delivery_time` | `Order.completion_time` |

**Missing from dataset:**
- `Order.prep_time` (no restaurant queue / ready time recorded)
- `Order.profit`
- `Driver.status` transitions within a shift

**`aoi_type` value counts (top 10):**

| aoi_type | Count |
| --- | --- |
| 1 | 620,956 |
| 14 | 193,610 |
| 4 | 43,353 |
| 0 | 32,436 |
| 7 | 14,993 |
| 15 | 4,880 |
| 3 | 4,546 |
| 2 | 3,861 |
| 12 | 3,672 |
| 13 | 3,558 |

> `aoi_type=1` and `aoi_type=14` dominate; unclear if these map to different merchant categories (e.g., restaurants vs. retail).

## 4. Temporal Patterns (Busy / Off-Peak Hours)

**Order volume by hour of acceptance (all dates):**

```
  04:00        2 ( 0.0%)  
  05:00       40 ( 0.0%)  
  06:00    3,139 ( 0.3%)  
  07:00   37,095 ( 4.0%)  ███
  08:00  192,696 (20.7%)  ███████████████████
  09:00   84,761 ( 9.1%)  ████████
  10:00   16,947 ( 1.8%)  █
  11:00   10,958 ( 1.2%)  █
  12:00    9,918 ( 1.1%)  █
  13:00  140,357 (15.1%)  ██████████████
  14:00  291,968 (31.3%)  ██████████████████████████████
  15:00   86,394 ( 9.3%)  ████████
  16:00   26,013 ( 2.8%)  ██
  17:00   12,515 ( 1.3%)  █
  18:00    8,235 ( 0.9%)  
  19:00    6,048 ( 0.6%)  
  20:00    2,700 ( 0.3%)  
  21:00    1,007 ( 0.1%)  
  22:00      435 ( 0.0%)  
  23:00      123 ( 0.0%)  
```
- **Peak hours** (top quartile by volume): [8, 9, 13, 14, 15]
- **Off-peak hours** (bottom quartile): [4, 5, 21, 22, 23]

**Unique dates in dataset:** 184  (501 … 1031)
- Orders per date: min=2,281  mean=5062  max=14,172

## 5. Spatial / Zone Structure

- Unique regions (zones): **48**
- Unique aoi_ids (pickup points / restaurants): **17,451**

**Top 10 regions by order volume:**

| region_id | orders | couriers | aois |
| --- | --- | --- | --- |
| 155 | 46,646 | 71 | 386 |
| 160 | 46,440 | 44 | 568 |
| 105 | 44,884 | 53 | 645 |
| 123 | 40,496 | 64 | 470 |
| 133 | 38,905 | 66 | 518 |
| 110 | 37,473 | 70 | 269 |
| 103 | 36,240 | 65 | 563 |
| 141 | 35,407 | 57 | 489 |
| 166 | 35,089 | 53 | 428 |
| 149 | 35,050 | 41 | 405 |

- AOIs per region: min=1  median=378  max=755
- Couriers per region: min=1  median=34  max=71

**Geographic bounding box:**
- lat: [28.4709, 39.9120]
- lng: [102.4721, 116.4061]

## 6. Ratio Analysis (Drivers : Restaurants : Zones)

**Global ratios:**

| Entity | Count | Per Zone |
| --- | --- | --- |
| Drivers | 1,494 | — |
| Restaurants | 17,451 | 364 |
| Zones | 48 | — |

Ratio drivers:restaurants:zones = **1 : 11.7 : 0.032**

**Largest region (region_id=155):**
- Orders: 46,646
- Drivers: 71
- Restaurants: 386
- Drivers:aois ratio = 1 : 5.4

## 7. Batching Detection

- Total consecutive-order pairs analysed: **862,830**
- Pairs where next accept < previous delivery: **809,625**
- Batching rate: **93.8%**
- Couriers observed batching at least once: **1,399 / 1,494**

**Time between consecutive order acceptances (same courier, same day):**

| Percentile | Minutes |
| --- | --- |
| p5 | 0.0 |
| p25 | 0.0 |
| p50 | 0.0 |
| p75 | 1.0 |
| p95 | 165.0 |

## 8. Driver Route Analysis

**Orders per courier (career total):**

| Percentile | Orders |
| --- | --- |
| min | 1 |
| p25 | 30 |
| p50 | 170 |
| p75 | 758 |
| max | 5205 |

**Orders per courier per day:**

| Percentile | Orders |
| --- | --- |
| p25 | 5 |
| p50 | 12 |
| p75 | 20 |
| p95 | 32 |

**Pickup-to-delivery straight-line distance (km, sample n=20,000):**

| Percentile | km |
| --- | --- |
| p25 | 0.03 |
| p50 | 0.07 |
| p75 | 0.17 |
| p95 | 1.48 |

- Courier×day×aoi groups with >1 order (revisits / multi-pickup): **170,538**
  (34.5% of all courier×day×aoi combos)

## 9. Model Fitness Summary

### Fits the Simulator Model

- Spatial coordinates for source, destination, and driver positions map directly to the new location fields.
- `region_id` → zone provides a natural zone hierarchy (48 zones).
- `aoi_id` → restaurant gives pickup-point identity.
- Hourly order volume shows clear peak / off-peak structure usable to calibrate arrival rate λ per hour.
- Batching signal is present: many couriers accepted a new order before completing the previous one.
- `accept_gps` captures driver location at assignment — can initialise `Driver.location` and validate GreedyNearest cost.

### Gaps / Concerns

- **No prep_time.** `accept_time` appears to be when the courier accepted the job, not when the order was placed or ready. A prep_time distribution must be assumed or sampled.
- **Very long delivery durations** (median ~3 h, p95 ~28 h). This is consistent with general-goods courier delivery, not food delivery. Consider whether the time scale matches simulation parameters, or whether durations should be rescaled / filtered.
- **No explicit order-ready event.** The queue wait between `accept_time` and actual pickup is unobservable unless trajectory data (`courier_detailed_trajectory.zip`) is used.
- **Restaurant count is very high** (17 k AOIs across 48 zones, ~360 per zone). If the simulator uses a small number of restaurants per zone, filter to a single region or cluster AOIs by proximity.
- **`aoi_type` semantics are unknown.** Type-1 (66%) and type-14 (21%) dominate; unclear whether all types represent food merchants.

### Recommended Next Steps

1. Filter to a single region (e.g., top-volume region) to reduce AOI count to a manageable range.
2. Inspect `courier_detailed_trajectory.zip` to see if in-route GPS traces reveal when couriers actually arrived at pickup (proxy for order ready time).
3. Decide on a prep_time model (fixed constant or fitted distribution) to fill the missing field.
4. Check whether `delivery_five_cities.csv` or `delivery_jl.csv` contain additional cities that could serve as out-of-sample validation sets.

## 10. GPS Coverage per AOI

### AOI count per courier

| Stat | Value |
| --- | --- |
| min | 1 |
| max | 428 |
| avg | 37.51 |

Each courier serves between 1 and 428 distinct AOIs over the dataset, averaging ~38.

### Unique accept GPS pairs per aoi_id

| Stat | Unique accept pairs |
| --- | --- |
| min | 1 |
| p25 | 2 |
| median | 6 |
| p75 | 11 |
| max | 39 |
| mean | 7.26 |

**Top 15 AOIs by unique accept GPS pairs:**

| aoi_id | unique accept pairs |
| --- | --- |
| 54286 | 39 |
| 8899 | 39 |
| 17089 | 36 |
| 25525 | 35 |
| 42234 | 33 |
| 13966 | 33 |
| 31869 | 30 |
| 43557 | 30 |
| 54778 | 29 |
| 52585 | 29 |
| 44741 | 29 |
| 49765 | 28 |
| 38404 | 28 |
| 3643 | 27 |
| 17684 | 27 |

> High accept-pair counts suggest busy AOIs where couriers are spread across many pickup positions, or GPS jitter across many orders at the same location.

### Unique delivery GPS pairs per aoi_id

| Stat | Unique delivery pairs |
| --- | --- |
| min | 1 |
| p25 | 3 |
| median | 9 |
| p75 | 33 |
| max | 2,324 |
| mean | 38.09 |

**Top 15 AOIs by unique delivery GPS pairs:**

| aoi_id | unique delivery pairs |
| --- | --- |
| 4261 | 2,324 |
| 33630 | 1,690 |
| 37094 | 1,649 |
| 19084 | 1,647 |
| 53019 | 1,567 |
| 14594 | 1,469 |
| 42595 | 1,384 |
| 38030 | 1,315 |
| 39441 | 1,290 |
| 20067 | 1,259 |
| 35192 | 1,252 |
| 22156 | 1,195 |
| 27999 | 1,165 |
| 43931 | 1,136 |
| 42238 | 1,087 |

> Delivery pairs spread far wider than accept pairs — consistent with one pickup location fanning out to many distinct customer addresses.

### Unique couriers per aoi_id

| Stat | Unique couriers |
| --- | --- |
| min | 1 |
| p25 | 1 |
| median | 2 |
| p75 | 4 |
| max | 29 |
| mean | 3.21 |

**Top 15 AOIs by unique couriers:**

| aoi_id | unique couriers |
| --- | --- |
| 36363 | 29 |
| 15435 | 26 |
| 13610 | 26 |
| 63 | 26 |
| 41402 | 25 |
| 32257 | 24 |
| 58184 | 24 |
| 19800 | 24 |
| 47022 | 23 |
| 44741 | 22 |
| 38393 | 22 |
| 56748 | 22 |
| 4261 | 22 |
| 11940 | 21 |
| 31265 | 21 |

## 11. Inter-Accept Time Analysis

For each courier, the gap between accept[i] and accept[i+1] is included **only** if accept[i+1] occurs before delivery[i] — i.e. the courier accepted a new order while the previous one was still undelivered. Gaps between a delivery and the next accept (idle time) are excluded.

**Distribution of time between consecutive accepts (while previous order still undelivered):**

| Percentile | Minutes |
| --- | --- |
| min | 0.0 |
| p5 | 0.0 |
| p25 | 0.0 |
| p50 | 0.0 |
| p75 | 1.0 |
| p90 | 2.0 |
| p95 | 8.0 |
| max | 930.0 |

- Total gaps analysed: **809,625**
- Gaps < 5 min: **754,574** (93.2%)
- Gaps 5–30 min: **32,056** (4.0%)
- Gaps 30–60 min: **5,695** (0.7%)
- Gaps > 60 min: **17,300** (2.1%)

**Per-courier mean inter-accept gap (minutes, couriers with ≥1 qualifying gap):**

| Percentile | Minutes |
| --- | --- |
| min | 0.0 |
| p25 | 1.8 |
| p50 | 4.1 |
| p75 | 7.4 |
| max | 187.3 |

- Couriers with at least one qualifying gap: **1,399**
- Couriers with mean gap < 5 min: **812**
- Couriers with mean gap > 30 min: **42**
