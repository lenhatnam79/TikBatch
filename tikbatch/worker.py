"""Isolated yt-dlp listing process, also usable inside a frozen application."""
import json
import sys


class Quiet:
    def debug(self, *args): pass
    def warning(self, *args): pass
    def error(self, *args): pass


def options(cookiefile=None):
    return {"quiet": True, "no_warnings": True, "logger": Quiet(),
            "socket_timeout": 12, "retries": 0, "extractor_retries": 0,
            "cachedir": False, "noplaylist": True,
            **({"cookiefile": str(cookiefile)} if cookiefile else {})}


def main(args=None):
    args = args if args is not None else sys.argv[1:]
    if args[0] == "install-browser":
        from playwright._impl._driver import compute_driver_executable, get_driver_env
        import subprocess
        node, cli = compute_driver_executable()
        return subprocess.call([str(node), str(cli), "install", "chromium"], env=get_driver_env())
    if args[0] != "scan":
        return 2
    import yt_dlp
    try:
        opts = options()
        opts.update({"extract_flat": True, "lazy_playlist": True, "noplaylist": False})
        with yt_dlp.YoutubeDL(opts) as ydl:
            if len(args) > 2:
                import http.cookiejar
                jar = http.cookiejar.MozillaCookieJar(args[2])
                jar.load(ignore_discard=True, ignore_expires=True)
                for cookie in jar:
                    ydl.cookiejar.set_cookie(cookie)
            listing = ydl.extract_info(args[1], download=False)
            count = 0
            for item in listing.get("entries", []):
                if not item:
                    raise RuntimeError("Danh sách chứa mục không đọc được.")
                print(json.dumps({"type": "video", "id": str(item["id"]),
                                  "url": item.get("webpage_url") or item.get("url"),
                                  "title": item.get("title") or "",
                                  "timestamp": item.get("timestamp") or 0}), flush=True)
                count += 1
            if not count:
                raise RuntimeError("Nguồn không trả về video; chưa xác nhận kênh trống.")
            print(json.dumps({"type": "end", "count": count}), flush=True)
        return 0
    except Exception:
        # Raw extractor exceptions may contain signed links or cookie information.
        print(json.dumps({"type": "error", "message": "Không lấy được toàn bộ danh sách bằng yt-dlp."}), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
