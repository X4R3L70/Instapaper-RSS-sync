import feedparser
import requests
from requests_oauthlib import OAuth1
import os
import json
import time

# --- CONFIGURATION ---
CONSUMER_KEY = os.environ.get('CONSUMER_KEY')
CONSUMER_SECRET = os.environ.get('CONSUMER_SECRET')
USER_EMAIL = os.environ.get('INSTAPAPER_USER')
USER_PASS = os.environ.get('INSTAPAPER_PASS')

RSS_FEED_URLS = [
    'https://www.franceinfo.fr/titres.rss',
    'https://www.bfmtv.com/rss/economie/',
    'https://www.ft.com/news-feed?format=rss',
    'https://feeds.arstechnica.com/arstechnica/index',
    'https://news.ycombinator.com/rss',
    'https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/portada',
    'https://www.monde-diplomatique.fr/rss/'
]
DB_FILE = 'article_data.json'

# --- API HELPERS ---
def get_oauth_token():
    """Obtains the OAuth token and secret for the user."""
    url = "https://www.instapaper.com/api/1.1/oauth/access_token"
    auth = OAuth1(CONSUMER_KEY, CONSUMER_SECRET)
    params = {'x_auth_username': USER_EMAIL, 'x_auth_password': USER_PASS, 'x_auth_mode': 'client_auth'}
    
    response = requests.post(url, auth=auth, data=params)
    parts = response.text.split('&')
    token = parts[0].split('=')[1]
    secret = parts[1].split('=')[1]
    return OAuth1(CONSUMER_KEY, CONSUMER_SECRET, token, secret)

def get_tracked_data():
    if not os.path.exists(DB_FILE):
        return {}
    try:
        with open(DB_FILE, 'r') as f:
            content = f.read().strip()
            return json.loads(content) if content else {}
    except:
        return {}

def save_tracked_data(data):
    with open(DB_FILE, 'w') as f:
        json.dump(data, f, indent=4)

# --- CORE FUNCTIONS ---
def add_new_articles(auth, tracked_data):
    for feed_url in RSS_FEED_URLS:
        print(f"Checking feed: {feed_url}")
        feed = feedparser.parse(feed_url)
        for entry in reversed(feed.entries):
            url = entry.link
            if url not in tracked_data:
                try:
                    res = requests.post("https://www.instapaper.com/api/1.1/bookmarks/add", auth=auth, data={'url': url}, timeout=15)
                    if res.status_code == 200:
                        data = res.json()
                        # The 'add' endpoint usually returns a list
                        if isinstance(data, list) and len(data) > 0:
                            tracked_data[url] = {
                                "added_at": time.time(), 
                                "id": data[0]['bookmark_id']
                            }
                            print(f"Added: {url}")
                    time.sleep(1)
                except Exception as e:
                    print(f"Error adding {url}: {e}")

def cleanup_old_articles(auth, tracked_data):
    """Cleanup logic that handles both List and Dictionary responses."""
    current_time = time.time()
    seconds_in_24h = 24 * 60 * 60
    unread_bookmarks = {}

    try:
        list_res = requests.post("https://www.instapaper.com/api/1.1/bookmarks/list", auth=auth, timeout=15)
        if list_res.status_code == 200:
            raw_data = list_res.json()
            
            # Logic apply: Handle the dictionary response seen in logs
            if isinstance(raw_data, dict) and 'bookmarks' in raw_data:
                bookmarks_list = raw_data['bookmarks']
            elif isinstance(raw_data, list):
                bookmarks_list = raw_data
            else:
                bookmarks_list = []

            for item in bookmarks_list:
                if isinstance(item, dict) and item.get('type') == 'bookmark':
                    unread_bookmarks[str(item['bookmark_id'])] = item
        else:
            print(f"Cleanup skipped: API returned status {list_res.status_code}")
            return tracked_data 
    except Exception as e:
        print(f"Cleanup error: {e}")
        return tracked_data

    updated_tracked_data = {}
    for url, info in tracked_data.items():
        # If item is less than 24h old, keep it in the JSON
        if current_time - info['added_at'] < seconds_in_24h:
            updated_tracked_data[url] = info
            continue
        
        # If older than 24h, check Instapaper status before purging
        bookmark_id = str(info.get('id'))
        if bookmark_id in unread_bookmarks:
            bookmark = unread_bookmarks[bookmark_id]
            # Only delete if NOT starred/liked
            if str(bookmark.get('starred')) == '0':
                print(f"Deleting unliked article: {url}")
                requests.post("https://www.instapaper.com/api/1.1/bookmarks/delete", auth=auth, data={'bookmark_id': bookmark_id})
            else:
                print(f"Keeping liked article: {url}")
        
        # Regardless of deletion, we remove it from article_data.json to keep it slim
        print(f"Purging {url} from local database.")

    return updated_tracked_data

def main():
    auth = get_oauth_token()
    tracked_data = get_tracked_data()
    add_new_articles(auth, tracked_data)
    tracked_data = cleanup_old_articles(auth, tracked_data)
    save_tracked_data(tracked_data)

if __name__ == "__main__":
    main()
