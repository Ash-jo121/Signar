import requests

HEADERS = {"User-Agent": "ThreadRadar/1.0"}


def scrape_reddit_page(url):
    response = requests.get(url, headers=HEADERS)
    print(response.status_code)
    if response.status_code == 200:
        post_data = response.json()
        print(post_data)
        # return {
        #     "id": post_data["data"]["id"],
        #     "title": post_data["data"]["title"],
        #     "body": post_data["data"].get("selftext", ""),
        #     "score": post_data["data"]["score"],
        # }
    else:
        return None  # error handling


if __name__ == "__main__":
    url = "https://www.reddit.com/r/pennystocks/comments/1ryo5gi.json"
    post_data = scrape_reddit_page(url)
    print(post_data)
