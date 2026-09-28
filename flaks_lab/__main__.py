"""python -m flaks_lab  → abre http://127.0.0.1:8765"""
import argparse
import threading
import webbrowser

import uvicorn


def main() -> None:
    ap = argparse.ArgumentParser(description="Flaks Content Lab")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()
    if not args.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(f"http://{args.host}:{args.port}")).start()
    uvicorn.run("flaks_lab.main:app", host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
