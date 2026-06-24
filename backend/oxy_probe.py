"""
Oxylabs Web Unblocker probe.

Goal: answer ONE question before touching the real pipeline —
does old.reddit.com/...new.json come back as parseable JSON through
the unblocker with rendering OFF?

Run:
    export OXY_USER=your_unblocker_user
    export OXY_PASS=your_unblocker_pass
    python3 oxy_probe.py

Costs only a few KB of trial traffic.
"""

import json
import os
import sys

import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning

requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

OXY_USER = ""
OXY_PASS = ""
# OXY_USER = os.getenv("OXY_USER")
# OXY_PASS = os.getenv("OXY_PASS")
if not OXY_USER or not OXY_PASS:
    sys.exit("Set OXY_USER and OXY_PASS environment variables first.")

UNBLOCKER = f"http://{OXY_USER}:{OXY_PASS}@unblock.oxylabs.io:60000"
PROXIES = {"http": UNBLOCKER, "https": UNBLOCKER}

# Same browser UA your fetcher uses, so the probe matches production conditions.
BASE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
}


def probe(label, url, render=None):
    headers = dict(BASE_HEADERS)
    if render:
        # Only set this if you WANT rendering. For raw JSON we leave it off.
        headers["X-Oxylabs-Render"] = render
    try:
        r = requests.get(
            url,
            proxies=PROXIES,
            headers=headers,
            verify=False,  # Web Unblocker does TLS interception; required.
            timeout=120,
        )
    except Exception as exc:
        print(f"[{label}] REQUEST FAILED: {exc}")
        return

    print(
        f"[{label}] status={r.status_code} bytes={len(r.content)} "
        f"render={render or 'off'}"
    )

    # The decisive check: is the body JSON we can parse the way the pipeline does?
    body = r.text
    try:
        data = json.loads(body)
        children = data.get("data", {}).get("children", [])
        print(f"          -> JSON OK: {len(children)} posts in listing")
        if children:
            first = children[0]["data"]
            print(
                f"          -> sample post id={first.get('id')} "
                f"title={first.get('title','')[:50]!r}"
            )
    except json.JSONDecodeError:
        print(f"          -> NOT JSON. First 200 chars of body:")
        print(f"             {body[:200]!r}")


# 0. Confirm the unblocker tunnel works at all + see an exit IP.
try:
    ip = requests.get(
        "https://ip.oxylabs.io/location",
        proxies=PROXIES,
        verify=False,
        timeout=60,
    )
    print(f"[tunnel] status={ip.status_code} body={ip.text[:160]}")
except Exception as exc:
    print(f"[tunnel] FAILED: {exc}")

print("-" * 60)

# 1. THE test: listing JSON, rendering OFF. This is what the pipeline needs.
probe("listing-json", "https://old.reddit.com/r/pennystocks/new.json?limit=5")

# 2. A comments JSON endpoint shape (uses a real post id if the listing gave one
#    you can paste; this static one may 404, that's fine — we only care whether
#    the RESPONSE is JSON vs an HTML block page).
probe(
    "comments-json",
    "https://old.reddit.com/r/pennystocks/comments/.json",
)
