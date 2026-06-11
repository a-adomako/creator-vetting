#!/usr/bin/env python3
"""
CreatorVetter — Instagram creator vetting pipeline.

Usage:
  python run.py --input input/creators.csv
  python run.py --input input/creators.csv --output output/my_run.csv
  python run.py --input input/creators.csv --config config/config.yaml

Input CSV must have a 'url' and/or 'username' column.
API key must be set in a .env file as MODASH_API_KEY.
"""

import argparse
import logging
import sys


def main():
    parser = argparse.ArgumentParser(
        description="Creator Vetter — Instagram profile analysis pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--input", required=True,
        help="Path to input CSV file (must contain 'url' and/or 'username' column)",
    )
    parser.add_argument(
        "--output",
        help="Output CSV path (default: output/enriched_<timestamp>.csv)",
    )
    parser.add_argument(
        "--config", default="config/config.yaml",
        help="Path to config YAML file (default: config/config.yaml)",
    )
    parser.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default: INFO)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        from src.pipeline import Pipeline
        pipeline = Pipeline(config_path=args.config)
        output_path = pipeline.run(input_path=args.input, output_path=args.output)
        print(f"\nOutput written to: {output_path}")
    except FileNotFoundError as e:
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"\nConfiguration error: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nInterrupted by user.", file=sys.stderr)
        sys.exit(130)


if __name__ == "__main__":
    main()
