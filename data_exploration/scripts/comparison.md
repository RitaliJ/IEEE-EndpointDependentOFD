# Delivery Dataset — Four-City Comparison

Cities: **cq** (Chongqing), **hz** (Hangzhou), **sh** (Shanghai), **yt** (Yantai)

## 1. Dataset Sizes & Column Overview

| City | Rows | Columns | Parse Errors |
| --- | --- | --- | --- |
| cq | 931,351 | 21 | 0 |
| hz | 1,861,600 | 21 | 0 |
| sh | 1,483,864 | 21 | 0 |
| yt | 206,431 | 21 | 0 |

**Unique counts per city:**

| City | Orders | Couriers | AOIs | Zones | Dates |
| --- | --- | --- | --- | --- | --- |
| cq | 931,351 | 1,494 | 17,451 | 48 | 184 |
| hz | 1,861,600 | 1,392 | 17,714 | 51 | 184 |
| sh | 1,483,864 | 1,733 | 15,564 | 52 | 184 |
| yt | 206,431 | 205 | 8,163 | 17 | 184 |

## 2. Delivery Duration Distribution

**Cross-midnight corrections and outliers:**

| City | Cross-midnight fixed | Neg. after fix | <10 min | >8 h | >24 h |
| --- | --- | --- | --- | --- | --- |
| cq | — | 3 | 19,801 | 95,139 | 31,231 |
| hz | — | 0 | 39,582 | 72,303 | 11,123 |
| sh | — | 0 | 33,524 | 36,628 | 3,578 |
| yt | — | 0 | 2,625 | 22,931 | 2,650 |

**Duration percentiles (minutes):**

| Percentile | cq | hz | sh | yt |
| --- | --- | --- | --- | --- |
| p5 | 29.0 | 19.0 | 17.0 | 40.0 |
| p25 | 83.0 | 61.0 | 43.0 | 114.0 |
| p50 | 151.0 | 115.0 | 72.0 | 208.0 |
| p75 | 256.0 | 197.0 | 119.0 | 344.0 |
| p95 | 745.0 | 424.0 | 322.0 | 597.0 |

## 3. Temporal Patterns (Hourly Order Volume)

**Orders per date (min / mean / max):**

| City | Date range | Min/day | Mean/day | Max/day |
| --- | --- | --- | --- | --- |
| cq | 501 – 1031 | 2,281 | 5062 | 14,172 |
| hz | 501 – 1031 | 5,953 | 10117 | 17,800 |
| sh | 501 – 1031 | 438 | 8064 | 17,381 |
| yt | 501 – 1031 | 603 | 1122 | 2,252 |

**Peak hours (top-quartile acceptance volume) per city:**

- **cq**: [8, 9, 13, 14, 15]
- **hz**: [7, 8, 9, 10, 15, 16]
- **sh**: [8, 9, 10, 11, 16]
- **yt**: [8, 9, 10, 11, 12]

**Hourly acceptance profiles (normalised % of daily total):**

```
  cq
    00:00   0.0%  
    01:00   0.0%  
    02:00   0.0%  
    03:00   0.0%  
    04:00   0.0%  
    05:00   0.0%  
    06:00   0.3%  
    07:00   4.0%  ██
    08:00  20.7%  █████████████
    09:00   9.1%  █████
    10:00   1.8%  █
    11:00   1.2%  
    12:00   1.1%  
    13:00  15.1%  █████████
    14:00  31.3%  ████████████████████
    15:00   9.3%  █████
    16:00   2.8%  █
    17:00   1.3%  
    18:00   0.9%  
    19:00   0.6%  
    20:00   0.3%  
    21:00   0.1%  
    22:00   0.0%  
    23:00   0.0%  
```
```
  hz
    00:00   0.0%  
    01:00   0.0%  
    02:00   0.0%  
    03:00   0.0%  
    04:00   0.0%  
    05:00   0.0%  
    06:00   0.2%  
    07:00  12.2%  ███████
    08:00  32.1%  ████████████████████
    09:00  11.5%  ███████
    10:00   4.5%  ██
    11:00   2.5%  █
    12:00   2.1%  █
    13:00   3.0%  █
    14:00   4.4%  ██
    15:00  13.0%  ████████
    16:00   7.3%  ████
    17:00   3.7%  ██
    18:00   2.3%  █
    19:00   0.9%  
    20:00   0.3%  
    21:00   0.1%  
    22:00   0.0%  
    23:00   0.0%  
```
```
  sh
    00:00   0.0%  
    01:00   0.0%  
    02:00   0.0%  
    03:00   0.0%  
    04:00   0.0%  
    05:00   0.0%  
    06:00   0.0%  
    07:00   1.1%  █
    08:00  12.0%  ████████████████
    09:00  14.4%  ████████████████████
    10:00  10.9%  ███████████████
    11:00   9.3%  ████████████
    12:00   6.8%  █████████
    13:00   6.0%  ████████
    14:00   7.2%  █████████
    15:00   8.6%  ███████████
    16:00   9.8%  █████████████
    17:00   6.0%  ████████
    18:00   4.3%  ██████
    19:00   2.1%  ██
    20:00   1.0%  █
    21:00   0.4%  
    22:00   0.1%  
    23:00   0.0%  
```
```
  yt
    00:00   0.0%  
    01:00   0.0%  
    02:00   0.0%  
    03:00   0.0%  
    04:00   0.0%  
    05:00   0.1%  
    06:00   0.6%  
    07:00   2.5%  █
    08:00  14.9%  █████████
    09:00  18.5%  ███████████
    10:00  31.1%  ████████████████████
    11:00  14.9%  █████████
    12:00   6.4%  ████
    13:00   3.6%  ██
    14:00   2.9%  █
    15:00   1.9%  █
    16:00   1.1%  
    17:00   0.7%  
    18:00   0.5%  
    19:00   0.2%  
    20:00   0.1%  
    21:00   0.1%  
    22:00   0.0%  
    23:00   0.0%  
```

## 4. Spatial / Zone Structure

**Bounding boxes:**

| City | lat min | lat max | lng min | lng max |
| --- | --- | --- | --- | --- |
| cq | 28.4709 | 39.9120 | 102.4721 | 116.4061 |
| hz | 23.1135 | 33.0491 | 113.4049 | 121.4420 |
| sh | 26.6990 | 39.9119 | 102.0849 | 121.9547 |
| yt | 36.5902 | 38.0163 | 119.6313 | 121.8881 |

**AOIs and couriers per zone (median across zones):**

| City | Zones | AOIs/zone (med) | Couriers/zone (med) |
| --- | --- | --- | --- |
| cq | 48 | 378 | 34 |
| hz | 51 | 269 | 25 |
| sh | 52 | 282 | 35 |
| yt | 17 | 475 | 10 |

**`aoi_type` composition (top 3 types, % of orders):**

- **cq**: type 1: 67%, type 14: 21%, type 4: 5%
- **hz**: type 1: 59%, type 14: 28%, type 0: 4%
- **sh**: type 1: 75%, type 14: 16%, type 0: 3%
- **yt**: type 1: 52%, type 14: 39%, type 7: 3%

## 5. Driver & Restaurant Ratios

| City | Drivers | Restaurants | Zones | Drivers:Restaurants | Drivers:Zones |
| --- | --- | --- | --- | --- | --- |
| cq | 1,494 | 17,451 | 48 | 1:11.7 | 1:0.032 |
| hz | 1,392 | 17,714 | 51 | 1:12.7 | 1:0.037 |
| sh | 1,733 | 15,564 | 52 | 1:9.0 | 1:0.030 |
| yt | 205 | 8,163 | 17 | 1:39.8 | 1:0.083 |

**Orders per courier (career total, percentiles):**

| Percentile | cq | hz | sh | yt |
| --- | --- | --- | --- | --- |
| p25 | 30 | 38 | 28 | 69 |
| p50 | 170 | 322 | 157 | 207 |
| p75 | 758 | 1817 | 956 | 1440 |
| p95 | 3047 | 5910 | 4149 | 4468 |

**Orders per courier per day (percentiles):**

| Percentile | cq | hz | sh | yt |
| --- | --- | --- | --- | --- |
| p25 | 5 | 17 | 8 | 1 |
| p50 | 12 | 25 | 21 | 8 |
| p75 | 20 | 35 | 32 | 19 |
| p95 | 32 | 49 | 45 | 34 |

## 6. Batching Rates

| City | Pairs | Batched pairs | Batch rate | Batching couriers | Gap p50 (min) | Gap p95 (min) |
| --- | --- | --- | --- | --- | --- | --- |
| cq | 862,830 | 809,625 | 93.8% | 1,399/1,494 | 0.0 | 165.0 |
| hz | 1,789,930 | 1,668,790 | 93.2% | 1,294/1,392 | 0.0 | 110.0 |
| sh | 1,413,611 | 1,234,465 | 87.3% | 1,635/1,733 | 1.0 | 140.0 |
| yt | 188,490 | 184,187 | 97.7% | 192/205 | 0.0 | 14.0 |

## 7. Route Distances (Straight-Line, km)

**Pickup → driver-at-accept distance:**

| City | n (sample) | median km | p95 km | max km |
| --- | --- | --- | --- | --- |
| cq | 10,000 | 2.44 | 6.48 | 180.42 |
| hz | 10,000 | 1.87 | 8.32 | 108.21 |
| sh | 10,000 | 1.70 | 4.75 | 18.72 |
| yt | 9,883 | 4.23 | 12.94 | 12641.14 |

**Pickup → delivery distance:**

| City | n (sample) | median km | p75 km | p95 km |
| --- | --- | --- | --- | --- |
| cq | 20,000 | 0.07 | 0.17 | 1.47 |
| hz | 20,000 | 0.05 | 0.13 | 0.98 |
| sh | 20,000 | 0.06 | 0.15 | 1.51 |
| yt | 20,000 | 0.10 | 0.27 | 2.89 |

## 8. Summary Comparison Table

| Metric | cq | hz | sh | yt |
| --- | --- | --- | --- | --- |
| Total orders | 931,351 | 1,861,600 | 1,483,864 | 206,431 |
| Unique couriers | 1,494 | 1,392 | 1,733 | 205 |
| Unique AOIs (restaurants) | 17,451 | 17,714 | 15,564 | 8,163 |
| Zones | 48 | 51 | 52 | 17 |
| Date range (days) | 184 | 184 | 184 | 184 |
| Delivery duration p50 | 151 min | 115 min | 72 min | 208 min |
| Delivery duration p95 | 745 min | 424 min | 322 min | 597 min |
| Batching rate | 93.8% | 93.2% | 87.3% | 97.7% |

### Key Differences

- **Scale:** sh (Shanghai) is substantially larger in orders and couriers; yt (Yantai) is the smallest city.
- **Duration:** All cities show long median durations (general-goods courier model, not food delivery). Check whether filtering by `aoi_type` yields shorter, more food-delivery-like trips.
- **Batching:** Rates are broadly similar across cities, indicating consistent multi-order courier behaviour in all markets.
- **Geography:** sh and hz have larger bounding boxes (denser urban areas); yt is more compact.
- **Zone granularity:** Zone counts vary per city — use per-city zone statistics rather than pooling when calibrating the simulator.
