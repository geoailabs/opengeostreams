"""OpenGeoStreams walkthrough. Run from the project root:

python -m examples.example --rows 1000 --dashboard
PNG export is opt-in: add --save-png (requires image-export dependencies).
"""
import argparse
from pathlib import Path
import opengeostreams as ogs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", nargs="?", default="Datasets/consolidated_dataset.csv")
    parser.add_argument("--rows", type=int, default=400)
    parser.add_argument("--parameter", default="pH")
    parser.add_argument("--dashboard", action="store_true")
    parser.add_argument("--save-png", action="store_true")
    args = parser.parse_args()
    data = ogs.load_csv(args.csv, rows=args.rows)
    print(data.head())
    print(data.summary)
    print(data.describe())
    print(data.describe(parameter=args.parameter))
    # The imported measurements are available as a pandas DataFrame.
    frame = data.data.copy()
    # Recombine disjoint slices without duplicating measurements.
    combined = ogs.concat([frame.iloc[:len(frame)//2], frame.iloc[len(frame)//2:]])
    print("Recombined measurements:", len(combined))
    if args.save_png:
        output = Path("outputs")
        output.mkdir(exist_ok=True)
        data.interpolate()
        for name in ("plot", "plot_trend", "plot_distribution", "plot_stream", "plot_map"):
            options = {"open_browser": False} if name == "plot_map" else {}
            getattr(data, name)(parameter=args.parameter, save_path=output / (name + ".png"), **options)
        print("Saved PNGs in", output.resolve())
    if args.dashboard:
        dashboard = data.dashboard()
        try:
            input("Press Enter to stop the dashboard. ")
        finally:
            dashboard.shutdown()
            dashboard.server_close()


if __name__ == "__main__":
    main()
