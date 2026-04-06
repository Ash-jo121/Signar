import requests
import os

PROXY_USER = ""
PROXY_PASS = ""

# Test different ports
ports = ["10001", "10000", "7777", "8080"]

test_url = "https://www.reddit.com/r/pennystocks/comments/1sb36bf.json"
HEADERS = {"User-Agent": "ThreadRadar/1.0"}

for port in ports:
    proxy_url = f"http://{PROXY_USER}:{PROXY_PASS}@gate.decodo.com:{port}"
    proxies = {"http": proxy_url, "https": proxy_url}

    try:
        r = requests.get(test_url, headers=HEADERS, proxies=proxies, timeout=15)
        print(f"Port {port}: {r.status_code} ✓")
    except Exception as e:
        print(f"Port {port}: FAILED — {str(e)[:60]}")
