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
  'https://www.ft.com/news-feed?format=rss'
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
    with open(DB_FILE, 'r') as f:
        return json.load(f)

def save_tracked_data(data):
    with open(DB_FILE, 'w') as f:
        json.dump(data, f, indent=4)

# --- CORE FUNCTIONS ---
def add_new_articles(auth, tracked_data):
    for feed_url in RSS_FEED_URLS:
        feed = feedparser.parse(feed_url)
        for entry in reversed(feed.entries):
            url = entry.link
            if url not in tracked_data:
                # Add to Instapaper
                res = requests.post("https://www.instapaper.com/api/1.1/bookmarks/add", auth=auth, data={'url': url})
                if res.status_code == 200:
                    print(f"Added: {url}")
                    # Store URL and current timestamp
                    tracked_data[url] = {"added_at": time.time(), "id": res.json()[0]['bookmark_id']}
                time.sleep(1)

def cleanup_old_articles(auth, tracked_data):
    current_time = time.time()
    seconds_in_24h = 24 * 60 * 60
    
    # Get current unread bookmarks to check status
    list_res = requests.post("https://www.instapaper.com/api/1.1/bookmarks/list", auth=auth)
    unread_bookmarks = {str(b['bookmark_id']): b for b in list_res.json() if b['type'] == 'bookmark'}

    urls_to_remove_from_db = []

    for url, info in tracked_data.items():
        # Check if 24 hours have passed
        if current_time - info['added_at'] > seconds_in_24h:
            bookmark_id = str(info['id'])
            
            # If it's still in the 'unread' list
            if bookmark_id in unread_bookmarks:
                bookmark = unread_bookmarks[bookmark_id]
                
                # If not starred (liked), delete it
                if bookmark['starred'] == '0':
                    print(f"Cleaning up unliked article: {url}")
                    requests.post("https://www.instapaper.com/api/1.1/bookmarks/delete", auth=auth, data={'bookmark_id': bookmark_id})
                else:
                    print(f"Keeping starred article: {url}")
            else:
                print(f"Article archived or already gone: {url}")
            
            urls_to_remove_from_db.append(url)

    # Remove processed items from local DB
    for url in urls_to_remove_from_db:
        del tracked_data[url]

def main():
    auth = get_oauth_token()
    tracked_data = get_tracked_data()
    
    # Step 1: Add new stuff
    add_new_articles(auth, tracked_data)
    
    # Step 2: Cleanup stuff older than 24h
    cleanup_old_articles(auth, tracked_data)
    
    save_tracked_data(tracked_data)

if __name__ == "__main__":
    main()
