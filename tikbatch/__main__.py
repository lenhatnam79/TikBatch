import argparse
import asyncio
import json
import signal
import sys
import threading
from pathlib import Path


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--worker":
        from .worker import main as worker_main
        return worker_main(sys.argv[2:])
    parser = argparse.ArgumentParser(description="TikBatch · Local TikTok downloader")
    parser.add_argument("--url", help="CLI: link kênh TikTok")
    parser.add_argument("--output", type=Path, help="CLI: thư mục lưu")
    parser.add_argument("--max-concurrent", type=int, default=16, choices=range(1, 17))
    parser.add_argument("--screenshot", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.url:
        if args.output is None:
            parser.error("--url cần --output")
        from .engine import Engine
        from .model import data_dir
        stop = threading.Event()
        signal.signal(signal.SIGINT, lambda *_: stop.set())
        def emit(kind, data):
            print(json.dumps({"event": kind, "data": data}, ensure_ascii=False), flush=True)
        result = asyncio.run(Engine(data_dir(), emit, stop, args.max_concurrent).run(args.url, args.output.resolve()))
        return 1 if result["error"] or result["failed"] or not result["scan"].startswith("source_end") else 0
    from .ui import launch
    return launch(args.screenshot)


if __name__ == "__main__":
    raise SystemExit(main())
