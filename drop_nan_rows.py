import sys
import pandas as pd
from pathlib import Path


def drop_nan_rows(input_path: str, output_path: str | None = None) -> None:
    path = Path(input_path)
    df = pd.read_csv(path)
    before = len(df)
    df = df.dropna()
    dropped = before - len(df)

    out = Path(output_path) if output_path else path.with_stem(path.stem + "_clean")
    df.to_csv(out, index=False)
    print(f"Dropped {dropped} rows with NaN ({before} → {len(df)}). Saved to {out}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python drop_nan_rows.py <input.csv> [output.csv]")
        sys.exit(1)
    drop_nan_rows(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
