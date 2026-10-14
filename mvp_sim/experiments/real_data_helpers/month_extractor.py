import argparse
import csv

START_MONTH: int = 6
END_MONTH:   int = 6
START_DAY:   int = 10
END_DAY:     int = 10

def in_range(ds: str) -> bool:
    """Return True if ds falls within [START_MONTH/START_DAY, END_MONTH/END_DAY] inclusive."""
    # ds format: MMDD (e.g. "1026" = October 26)
    val = int(ds)
    start = START_MONTH * 100 + START_DAY
    end   = END_MONTH   * 100 + END_DAY
    return start <= val <= end

def main() -> None:
    parser = argparse.ArgumentParser(description="Extract orders within a month range from a delivery CSV")
    parser.add_argument("input",  help="Path to input CSV")
    parser.add_argument("output", help="Path to output CSV")
    args = parser.parse_args()

    with open(args.input, newline="") as f:
        rows = list(csv.DictReader(f))

    filtered = [row for row in rows if in_range(row["ds"])]
    if not filtered:
        raise SystemExit(f"No rows found between {START_MONTH}/{START_DAY} and {END_MONTH}/{END_DAY}")

    with open(args.output, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(filtered)

    print(f"Wrote {len(filtered)} rows → {args.output}")

if __name__ == "__main__":
    main()
