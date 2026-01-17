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
    """Obtient le token OAuth pour l'utilisateur."""
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
        print(f"Vérification du flux : {feed_url}")
        feed = feedparser.parse(feed_url)
        for entry in reversed(feed.entries):
            url = entry.link
            if url not in tracked_data:
                try:
                    res = requests.post("https://www.instapaper.com/api/1.1/bookmarks/add", auth=auth, data={'url': url}, timeout=15)
                    if res.status_code == 200:
                        data = res.json()
                        if isinstance(data, list) and len(data) > 0:
                            # MODIFICATION : On enregistre la source pour le tri futur
                            tracked_data[url] = {
                                "added_at": time.time(), 
                                "id": data[0]['bookmark_id'],
                                "source": feed_url 
                            }
                            print(f"Ajouté : {url}")
                    time.sleep(1)
                except Exception as e:
                    print(f"Erreur lors de l'ajout de {url}: {e}")
                    
def cleanup_old_articles(auth, tracked_data):
    """Garde les 10 plus récents par source, sauf si l'article est marqué en favori."""
    
    # --- ÉTAPE 1 : Récupérer l'état actuel sur Instapaper ---
    unread_bookmarks = {}
    try:
        list_res = requests.post("https://www.instapaper.com/api/1.1/bookmarks/list", auth=auth, timeout=15)
        if list_res.status_code == 200:
            raw_data = list_res.json()
            # On gère les différents formats de réponse possibles
            bookmarks_list = raw_data.get('bookmarks', []) if isinstance(raw_data, dict) else raw_data
            for item in bookmarks_list:
                if isinstance(item, dict) and item.get('type') == 'bookmark':
                    unread_bookmarks[str(item['bookmark_id'])] = item
    except Exception as e:
        print(f"Erreur de synchronisation avec Instapaper: {e}")
        return tracked_data # On annule le nettoyage en cas d'erreur API pour ne rien perdre

    # --- ÉTAPE 2 : Regrouper par source ---
    articles_by_source = {}
    for url, info in tracked_data.items():
        source = info.get('source', 'unknown')
        if source not in articles_by_source:
            articles_by_source[source] = []
        
        article_info = info.copy()
        article_info['url'] = url
        articles_by_source[source].append(article_info)

    updated_tracked_data = {}

    # --- ÉTAPE 3 : Trier et filtrer ---
    for source, articles in articles_by_source.items():
        # Trier du plus récent au plus ancien
        articles.sort(key=lambda x: x['added_at'], reverse=True)

        for index, item in enumerate(articles):
            bookmark_id = str(item['id'])
            url = item.pop('url')
            
            # Vérifier si l'article est liké sur Instapaper
            is_starred = False
            if bookmark_id in unread_bookmarks:
                is_starred = str(unread_bookmarks[bookmark_id].get('starred')) == '1'

            # LOGIQUE DE CONSERVATION :
            # On garde si : c'est l'un des 10 premiers OU s'il est liké
            if index < 10 or is_starred:
                updated_tracked_data[url] = item
                if is_starred and index >= 10:
                    print(f"Conservation (Favori) : {url}")
            else:
                # Sinon, on supprime
                print(f"Suppression (Limite de 10 dépassée) : {url}")
                try:
                    requests.post("https://www.instapaper.com/api/1.1/bookmarks/delete", 
                                  auth=auth, data={'bookmark_id': bookmark_id}, timeout=15)
                except Exception as e:
                    print(f"Erreur suppression {url}: {e}")

    return updated_tracked_data

def main():
    auth = get_oauth_token()
    tracked_data = get_tracked_data()
    
    # Étape 1 : Ajouter les nouveaux articles
    add_new_articles(auth, tracked_data)
    
    # Étape 2 : Appliquer la règle des 10 articles max par source
    tracked_data = cleanup_old_articles(auth, tracked_data)
    
    # Étape 3 : Sauvegarder l'état actuel
    save_tracked_data(tracked_data)

if __name__ == "__main__":
    main()
