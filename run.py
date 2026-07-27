#!/usr/bin/env python3
"""
run.py — ePOV
Start the web interface.

Usage:
    python run.py
    python run.py --port 8001
    python run.py --host 0.0.0.0

Note: Run build.py first to generate the occurrence data.
"""
import argparse, sys, logging
from pathlib import Path

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S")

def main():
    parser = argparse.ArgumentParser(description="ePOV web interface")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    csv_dir = Path(__file__).parent / "data" / "output"
    if not any(csv_dir.glob("epov_occurrences_*.csv")):
        print("No occurrence data found. Run: python build.py")
        print("The interface will start but will return no results until the data is built.")

    try:
        import uvicorn
    except ImportError:
        print("uvicorn not installed. Run: pip install uvicorn[standard]")
        sys.exit(1)

    uvicorn.run("app.api:app", host=args.host, port=args.port,
                reload=args.reload, log_level="info")

if __name__ == "__main__":
    main()
