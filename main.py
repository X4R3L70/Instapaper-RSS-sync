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
    """Parses feeds and adds new articles with improved error checking."""
    for feed_url in RSS_FEED_URLS:
        print(f"Checking feed: {feed_url}")
        feed = feedparser.parse(feed_url)
        for entry in reversed(feed.entries):
            url = entry.link
            if url not in tracked_data:
                try:
                    res = requests.post("https://www.instapaper.com/api/1.1/bookmarks/add", auth=auth, data={'url': url}, timeout=15)
                    
                    if res.status_code == 200:
                        # Ensure the response actually contains bookmark data
                        data = res.json()
                        if isinstance(data, list) and len(data) > 0:
                            print(f"Successfully Added: {url}")
                            tracked_data[url] = {
                                "added_at": time.time(), 
                                "id": data[0]['bookmark_id']
                            }
                        else:
                            print(f"Warning: Instapaper added {url} but returned unusual data format.")
                    else:
                        print(f"Failed to add {url}. Status: {res.status_code}")
                        
                except Exception as e:
                    print(f"Error adding {url}: {e}")
                
                time.sleep(2) # Increased delay to avoid rate limiting during big initial syncs

def cleanup_old_articles(auth, tracked_data):
    """Cleanup logic with better handling of Instapaper's response list."""
    current_time = time.time()
    seconds_in_24h = 24 * 60 * 60
    unread_bookmarks = {}

    try:
        list_res = requests.post("https://www.instapaper.com/api/1.1/bookmarks/list", auth=auth, timeout=15)
        if list_res.status_code == 200:
            raw_data = list_res.json()
            # Instapaper API returns a list where the first item is often user info, not a bookmark
            for item in raw_data:
                if isinstance(item, dict) and item.get('type') == 'bookmark':
                    unread_bookmarks[str(item['bookmark_id'])] = item
        else:
            print(f"Cleanup skipped: API returned status {list_res.status_code}")
            return tracked_data # Return original data if API fails
    except Exception as e:
        print(f"Cleanup error (Instapaper might be down): {e}")
        return tracked_data

    updated_tracked_data = {}
    for url, info in tracked_data.items():
        if current_time - info['added_at'] > seconds_in_24h:
            bookmark_id = str(info.get('id'))
            if bookmark_id in unread_bookmarks:
                bookmark = unread_bookmarks[bookmark_id]
                if bookmark.get('starred') == '0':
                    print(f"Deleting unliked article: {url}")
                    requests.post("https://www.instapaper.com/api/1.1/bookmarks/delete", auth=auth, data={'bookmark_id': bookmark_id})
            # Item is purged from JSON regardless of if it was deleted on Instapaper
        else:
            updated_tracked_data[url] = info
            
    return updated_tracked_data
    
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
