import requests

PROXY_USER = ""
PROXY_PASS = ""
PROXY_HOST = ""
PROXY_PORT = ""

proxies = {
    "http": f"http://{PROXY_USER}:{PROXY_PASS}@{PROXY_HOST}:{PROXY_PORT}",
    "https": f"http://{PROXY_USER}:{PROXY_PASS}@{PROXY_HOST}:{PROXY_PORT}",
}

HEADERS = {"User-Agent": "ThreadRadar/1.0"}

# Test 1 — basic Reddit access
r1 = requests.get(
    "https://www.reddit.com/r/pennystocks/new.json?limit=5",
    headers=HEADERS,
    proxies=proxies,
    timeout=30,
)
print(f"Reddit status: {r1.status_code}")
if r1.status_code == 200:
    posts = r1.json()["data"]["children"]
    print(f"Posts fetched: {len(posts)}")
    print(f"First post: {posts[0]['data']['title'][:50]}")

# Test 2 — check your IP being used
r2 = requests.get("https://ip.decodo.com/json", proxies=proxies, timeout=30)
print(f"\nProxy IP info: {r2.json()}")
