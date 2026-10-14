import argparse
import csv
from collections import Counter

MONTH: int = 9   # 1–12

# How to measure "busiest": "orders" = most rows, "couriers" = most unique couriers
METRIC: str = "orders"

def main() -> None:
    parser = argparse.ArgumentParser(description="Extract the busiest day from a delivery CSV")
    parser.add_argument("input",  help="Path to input CSV")
    parser.add_argument("output", help="Path to output CSV")
    args = parser.parse_args()

    with open(args.input, newline="") as f:
        rows = list(csv.DictReader(f))

    month_prefix = f"{MONTH:02d}"
    rows = [row for row in rows if row["ds"].startswith(month_prefix)]
    if not rows:
        raise SystemExit(f"No rows found for month {MONTH:02d}")

    if METRIC == "orders":
        counts: Counter = Counter(row["ds"] for row in rows)
    elif METRIC == "couriers":
        seen: dict[str, set[str]] = {}
        for row in rows:
            seen.setdefault(row["ds"], set()).add(row["courier_id"])
        counts = Counter({ds: len(couriers) for ds, couriers in seen.items()})
    else:
        raise ValueError(f"Unknown METRIC: {METRIC!r}. Use 'orders' or 'couriers'.")

    busiest_day = counts.most_common(1)[0][0]
    print(f"Busiest day in month {MONTH:02d} (ds={busiest_day}): {counts[busiest_day]} {METRIC}")

    filtered = [row for row in rows if row["ds"] == busiest_day]

    with open(args.output, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(filtered)

    print(f"Wrote {len(filtered)} rows → {args.output}")

if __name__ == "__main__":
    main()
