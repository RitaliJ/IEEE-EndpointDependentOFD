import argparse
import csv

DECIMAL_PLACES: int = 4

def main() -> None:
    parser = argparse.ArgumentParser(description="Round accept_gps_lat/lng in a delivery CSV")
    parser.add_argument("input",  help="Path to input CSV")
    parser.add_argument("output", help="Path to output CSV")
    args = parser.parse_args()

    with open(args.input, newline="") as f_in, open(args.output, "w", newline="") as f_out:
        reader = csv.DictReader(f_in)
        writer = csv.DictWriter(f_out, fieldnames=reader.fieldnames or [])
        writer.writeheader()
        for row in reader:
            row["accept_gps_lng"] = round(float(row["accept_gps_lng"]), DECIMAL_PLACES)
            row["accept_gps_lat"] = round(float(row["accept_gps_lat"]), DECIMAL_PLACES)
            writer.writerow(row)

if __name__ == "__main__":
    main()
