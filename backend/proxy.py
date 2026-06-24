import requests

# Fill these in with your live Decodo credentials before running.
PROXY_USER = ""
PROXY_PASS = ""
PROXY_HOST = ""
PROXY_PORT = ""

proxies = {
    "http": f"http://{PROXY_USER}:{PROXY_PASS}@{PROXY_HOST}:{PROXY_PORT}",
    "https": f"http://{PROXY_USER}:{PROXY_PASS}@{PROXY_HOST}:{PROXY_PORT}",
}

# A realistic browser UA. "ThreadRadar/1.0" is exactly what Reddit's
# bot screen flags, so don't test with it.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def check(label, url, is_json):
    try:
        r = requests.get(url, headers=HEADERS, proxies=proxies, timeout=30)
        body = r.text[:120].replace("\n", " ")
        print(f"[{label}] status={r.status_code} url={r.url}")
        if r.status_code == 200 and is_json:
            try:
                posts = r.json()["data"]["children"]
                print(f"          -> {len(posts)} posts OK")
            except Exception as exc:
                print(f"          -> 200 but JSON parse failed: {exc}")
        elif r.status_code != 200:
            print(f"          body: {body}")
    except Exception as exc:
        print(f"[{label}] REQUEST FAILED: {exc}")


# 0. Exit IP first — runs even if Reddit blocks everything.
try:
    ip = requests.get("https://ip.decodo.com/json", proxies=proxies, timeout=30)
    print(f"[exit-ip] {ip.status_code} {ip.text[:200]}")
except Exception as exc:
    print(f"[exit-ip] FAILED (proxy itself is down/exhausted): {exc}")

print("-" * 60)

# 1. JSON surface (what proxy.py originally tested).
check("www-json", "https://www.reddit.com/r/pennystocks/new.json?limit=5", True)

# 2. old.reddit JSON (closer to your warmup target).
check("old-json", "https://old.reddit.com/r/pennystocks/new.json?limit=5", True)

# 3. old.reddit HTML — this is the exact surface that 403'd in your fetch warmup.
check("old-html", "https://old.reddit.com/r/pennystocks/", False)
