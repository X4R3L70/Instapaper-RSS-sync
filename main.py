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
    'https://www.ft.com/news-feed?format=rss', # Added missing comma
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
    """Load tracking data; handles non-existent or empty files safely."""
    if not os.path.exists(DB_FILE):
        return {}
    try:
        with open(DB_FILE, 'r') as f:
            content = f.read().strip()
            if not content:
                return {}
            return json.loads(content)
    except (json.JSONDecodeError, IOError):
        return {}

def save_tracked_data(data):
    """Saves the tracking data back to JSON."""
    with open(DB_FILE, 'w') as f:
        json.dump(data, f, indent=4)

# --- CORE FUNCTIONS ---
def add_new_articles(auth, tracked_data):
    """Parses feeds and adds new articles to Instapaper."""
    for feed_url in RSS_FEED_URLS:
        print(f"Checking feed: {feed_url}")
        feed = feedparser.parse(feed_url)
        for entry in reversed(feed.entries):
            url = entry.link
            if url not in tracked_data:
                # Add to Instapaper
                res = requests.post("https://www.instapaper.com/api/1.1/bookmarks/add", auth=auth, data={'url': url})
                if res.status_code == 200:
                    print(f"Added to Instapaper: {url}")
                    # Store URL, current timestamp, and ID
                    tracked_data[url] = {
                        "added_at": time.time(), 
                        "id": res.json()[0]['bookmark_id']
                    }
                time.sleep(1) # Be polite to the API

def cleanup_old_articles(auth, tracked_data):
    """Removes unliked articles from Instapaper and purges entries from local JSON after 24h."""
    current_time = time.time()
    seconds_in_24h = 24 * 60 * 60
    
    # 1. Fetch current unread bookmarks to check "Starred" status
    try:
        list_res = requests.post("https://www.instapaper.com/api/1.1/bookmarks/list", auth=auth, timeout=15)
        # Handle cases where API might return a list or error
        raw_list = list_res.json()
        unread_bookmarks = {str(b['bookmark_id']): b for b in raw_list if isinstance(b, dict) and b.get('type') == 'bookmark'}
    except Exception as e:
        print(f"Warning: Could not fetch unread list for cleanup: {e}")
        unread_bookmarks = {}

    updated_tracked_data = {}

    for url, info in tracked_data.items():
        # Check if 24 hours have passed since it was added to the DB
        if current_time - info['added_at'] > seconds_in_24h:
            bookmark_id = str(info['id'])
            
            # If the article is still unread in Instapaper
            if bookmark_id in unread_bookmarks:
                bookmark = unread_bookmarks[bookmark_id]
                
                # If NOT liked (starred == '0'), delete from Instapaper
                if bookmark.get('starred') == '0':
                    print(f"Deleting unliked article from Instapaper: {url}")
                    requests.post("https://www.instapaper.com/api/1.1/bookmarks/delete", auth=auth, data={'bookmark_id': bookmark_id})
                else:
                    print(f"Keeping liked article in Instapaper: {url}")
            else:
                print(f"Article {url} already archived/deleted by user.")
            
            # We DO NOT add this to updated_tracked_data, effectively purging it from the JSON
            print(f"Purging {url} from local database (24h reached).")
        else:
            # Keep it in the JSON for now
            updated_tracked_data[url] = info

    return updated_tracked_data

def main():
    auth = get_oauth_token()
    tracked_data = get_tracked_data()
    
    # Step 1: Add new stuff from feeds
    add_new_articles(auth, tracked_data)
    
    # Step 2: Clean up Instapaper and purge local JSON entries > 24h old
    tracked_data = cleanup_old_articles(auth, tracked_data)
    
    # Step 3: Save the slimmed-down JSON
    save_tracked_data(tracked_data)

if __name__ == "__main__":
    main()
