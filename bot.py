import os
import re
import math
import logging
import html
import requests
import random
import asyncio
import sqlite3
import json
from datetime import datetime
from urllib.parse import quote, urlencode
from typing import Dict, List, Set, Optional
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from deep_translator import GoogleTranslator

# ──────────────────────────
# Logging
# ──────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ──────────────────────────
# Token via variable d'environnement
# ──────────────────────────
TOKEN = os.getenv("TOKEN")

# ──────────────────────────
# Configuration
# ──────────────────────────
STREAMING_SITES = [
    {
        "name": "VoirAnime",
        "base_url": "https://voiranime.com",
        "search_url": "https://voiranime.com/?s={query}",
        "anime_url": "https://voiranime.com/anime/{slug}"
    },
    {
        "name": "Anime-Sama",
        "base_url": "https://www.anime-sama.fr",
        "search_url": "https://www.anime-sama.fr/search/?q={query}",
        "anime_url": "https://www.anime-sama.fr/anime/{slug}"
    },
    {
        "name": "French-Anime",
        "base_url": "https://french-anime.com",
        "search_url": "https://french-anime.com/search?q={query}",
        "anime_url": "https://french-anime.com/anime/{slug}"
    },
    {
        "name": "Franime",
        "base_url": "https://franime.fr",
        "search_url": "https://franime.fr/?s={query}",
        "anime_url": "https://franime.fr/anime/{slug}"
    },
    {
        "name": "Anime-Ultime",
        "base_url": "https://www.anime-ultime.net",
        "search_url": "https://www.anime-ultime.net/search-0-0-{query}.html",
        "anime_url": "https://www.anime-ultime.net/anime-{id}-0/infos.html"
    }
]

# Configuration Nautiljon
NAUTILJON_BASE_URL = "https://www.nautiljon.com"
NAUTILJON_SEARCH_URL = f"{NAUTILJON_BASE_URL}/recherche/"
# Cache pour les recherches Nautiljon
nautiljon_cache = {}

# ──────────────────────────
# Base de données
# ──────────────────────────
class AnimeDatabase:
    def __init__(self, db_path="anime_bot.db"):
        self.db_path = db_path
        self.init_db()

    def init_db(self):
        """Initialise la base de données avec les tables nécessaires"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        # Table des utilisateurs
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                language_code TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        # Table des favoris
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS favorites (
                user_id INTEGER,
                anime_id INTEGER,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, anime_id),
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        # Table des listes de visionnage
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS watchlists (
                user_id INTEGER,
                anime_id INTEGER,
                status TEXT CHECK(status IN ('plan_to_watch', 'watching', 'completed', 'dropped')),
                score INTEGER CHECK(score >= 0 AND score <= 10),
                progress INTEGER DEFAULT 0,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, anime_id),
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        # Table des listes personnalisées
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS custom_lists (
                list_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                list_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        # Table des animes dans les listes personnalisées
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS custom_list_items (
                list_id INTEGER,
                anime_id INTEGER,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (list_id, anime_id),
                FOREIGN KEY (list_id) REFERENCES custom_lists (list_id)
            )
        ''')
        # Table des achievements
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS achievements (
                achievement_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                achievement_type TEXT,
                achievement_name TEXT,
                achieved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        # Table du cache des animes
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS anime_cache (
                anime_id INTEGER PRIMARY KEY,
                title TEXT,
                title_japanese TEXT,
                title_english TEXT,
                image_url TEXT,
                synopsis TEXT,
                score REAL,
                episodes INTEGER,
                status TEXT,
                year INTEGER,
                genres TEXT,
                studios TEXT,
                producers TEXT,
                duration TEXT,
                rating TEXT,
                source TEXT,
                cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        # Table du cache des personnages
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS character_cache (
                character_id INTEGER PRIMARY KEY,
                name TEXT,
                name_kanji TEXT,
                about TEXT,
                image_url TEXT,
                favorites INTEGER,
                animeography TEXT,
                voice_actors TEXT,
                cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        conn.close()

    def add_user(self, user_id, username, first_name, last_name, language_code):
        """Ajoute un utilisateur à la base de données"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR IGNORE INTO users (user_id, username, first_name, last_name, language_code)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, username, first_name, last_name, language_code))
        conn.commit()
        conn.close()

    def add_to_favorites(self, user_id, anime_id):
        """Ajoute un anime aux favoris de l'utilisateur"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO favorites (user_id, anime_id)
            VALUES (?, ?)
        ''', (user_id, anime_id))
        conn.commit()
        conn.close()

    def remove_from_favorites(self, user_id, anime_id):
        """Retire un anime des favoris de l'utilisateur"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            DELETE FROM favorites 
            WHERE user_id = ? AND anime_id = ?
        ''', (user_id, anime_id))
        conn.commit()
        conn.close()

    def get_favorites(self, user_id):
        """Récupère les favoris de l'utilisateur"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT anime_id FROM favorites 
            WHERE user_id = ?
            ORDER BY added_at DESC
        ''', (user_id,))
        results = [row[0] for row in cursor.fetchall()]
        conn.close()
        return results

    def is_favorite(self, user_id, anime_id):
        """Vérifie si un anime est dans les favoris de l'utilisateur"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT COUNT(*) FROM favorites 
            WHERE user_id = ? AND anime_id = ?
        ''', (user_id, anime_id))
        result = cursor.fetchone()[0] > 0
        conn.close()
        return result

    def update_watchlist(self, user_id, anime_id, status, score=None, progress=None):
        """Met à jour la liste de visionnage de l'utilisateur"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        if score is not None and progress is not None:
            cursor.execute('''
                INSERT OR REPLACE INTO watchlists (user_id, anime_id, status, score, progress, updated_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ''', (user_id, anime_id, status, score, progress))
        elif score is not None:
            cursor.execute('''
                INSERT OR REPLACE INTO watchlists (user_id, anime_id, status, score, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ''', (user_id, anime_id, status, score))
        elif progress is not None:
            cursor.execute('''
                INSERT OR REPLACE INTO watchlists (user_id, anime_id, status, progress, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ''', (user_id, anime_id, status, progress))
        else:
            cursor.execute('''
                INSERT OR REPLACE INTO watchlists (user_id, anime_id, status, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ''', (user_id, anime_id, status))
        conn.commit()
        conn.close()

    def get_watchlist(self, user_id, status=None):
        """Récupère la liste de visionnage de l'utilisateur"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        if status:
            cursor.execute('''
                SELECT anime_id, status, score, progress FROM watchlists 
                WHERE user_id = ? AND status = ?
                ORDER BY updated_at DESC
            ''', (user_id, status))
        else:
            cursor.execute('''
                SELECT anime_id, status, score, progress FROM watchlists 
                WHERE user_id = ?
                ORDER BY updated_at DESC
            ''', (user_id,))
        results = []
        for row in cursor.fetchall():
            results.append({
                'anime_id': row[0],
                'status': row[1],
                'score': row[2],
                'progress': row[3]
            })
        conn.close()
        return results

    def get_watch_status(self, user_id, anime_id):
        """Récupère le statut de visionnage d'un anime pour un utilisateur"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT status, score, progress FROM watchlists 
            WHERE user_id = ? AND anime_id = ?
        ''', (user_id, anime_id))
        result = cursor.fetchone()
        conn.close()
        if result:
            return {
                'status': result[0],
                'score': result[1],
                'progress': result[2]
            }
        return None

    def create_custom_list(self, user_id, list_name):
        """Crée une liste personnalisée pour l'utilisateur"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO custom_lists (user_id, list_name)
            VALUES (?, ?)
        ''', (user_id, list_name))
        list_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return list_id

    def add_to_custom_list(self, list_id, anime_id):
        """Ajoute un anime à une liste personnalisée"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR IGNORE INTO custom_list_items (list_id, anime_id)
            VALUES (?, ?)
        ''', (list_id, anime_id))
        conn.commit()
        conn.close()

    def remove_from_custom_list(self, list_id, anime_id):
        """Retire un anime d'une liste personnalisée"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            DELETE FROM custom_list_items 
            WHERE list_id = ? AND anime_id = ?
        ''', (list_id, anime_id))
        conn.commit()
        conn.close()

    def get_custom_lists(self, user_id):
        """Récupère les listes personnalisées de l'utilisateur"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT list_id, list_name FROM custom_lists 
            WHERE user_id = ?
            ORDER BY created_at DESC
        ''', (user_id,))
        results = []
        for row in cursor.fetchall():
            results.append({
                'list_id': row[0],
                'list_name': row[1]
            })
        conn.close()
        return results

    def get_custom_list_items(self, list_id):
        """Récupère les animes d'une liste personnalisée"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT anime_id FROM custom_list_items 
            WHERE list_id = ?
            ORDER BY added_at DESC
        ''', (list_id,))
        results = [row[0] for row in cursor.fetchall()]
        conn.close()
        return results

    def add_achievement(self, user_id, achievement_type, achievement_name):
        """Ajoute un achievement à l'utilisateur"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        # Vérifie si l'achievement existe déjà
        cursor.execute('''
            SELECT COUNT(*) FROM achievements 
            WHERE user_id = ? AND achievement_type = ?
        ''', (user_id, achievement_type))
        if cursor.fetchone()[0] == 0:
            cursor.execute('''
                INSERT INTO achievements (user_id, achievement_type, achievement_name)
                VALUES (?, ?, ?)
            ''', (user_id, achievement_type, achievement_name))
            conn.commit()
            conn.close()
            return True
        conn.close()
        return False

    def get_achievements(self, user_id):
        """Récupère les achievements de l'utilisateur"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT achievement_type, achievement_name, achieved_at 
            FROM achievements 
            WHERE user_id = ?
            ORDER BY achieved_at DESC
        ''', (user_id,))
        results = []
        for row in cursor.fetchall():
            results.append({
                'type': row[0],
                'name': row[1],
                'achieved_at': row[2]
            })
        conn.close()
        return results

    def cache_anime(self, anime_data):
        """Met en cache les données d'un anime"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        # Convertir les listes en JSON pour le stockage
        genres_json = json.dumps([g['name'] for g in anime_data.get('genres', [])])
        studios_json = json.dumps([s['name'] for s in anime_data.get('studios', [])])
        producers_json = json.dumps([p['name'] for p in anime_data.get('producers', [])])
        # Gérer les images correctement
        images = anime_data.get('images', {})
        image_url = None
        if images.get('jpg'):
            image_url = images['jpg'].get('large_image_url') or images['jpg'].get('image_url')
        cursor.execute('''
            INSERT OR REPLACE INTO anime_cache 
            (anime_id, title, title_japanese, title_english, image_url, synopsis, 
             score, episodes, status, year, genres, studios, producers, duration, rating, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            anime_data.get('mal_id'),
            anime_data.get('title'),
            anime_data.get('title_japanese'),
            anime_data.get('title_english'),
            image_url,
            anime_data.get('synopsis'),
            anime_data.get('score'),
            anime_data.get('episodes'),
            anime_data.get('status'),
            anime_data.get('year'),
            genres_json,
            studios_json,
            producers_json,
            anime_data.get('duration'),
            anime_data.get('rating'),
            anime_data.get('source')
        ))
        conn.commit()
        conn.close()

    def get_cached_anime(self, anime_id):
        """Récupère un anime depuis le cache"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM anime_cache WHERE anime_id = ?
        ''', (anime_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            # Reconstruire l'objet anime à partir des données en cache
            return {
                'mal_id': row[0],
                'title': row[1],
                'title_japanese': row[2],
                'title_english': row[3],
                'images': {'jpg': {'image_url': row[4], 'large_image_url': row[4]}},
                'synopsis': row[5],
                'score': row[6],
                'episodes': row[7],
                'status': row[8],
                'year': row[9],
                'genres': [{'name': name} for name in json.loads(row[10])],
                'studios': [{'name': name} for name in json.loads(row[11])],
                'producers': [{'name': name} for name in json.loads(row[12])],
                'duration': row[13],
                'rating': row[14],
                'source': row[15]
            }
        return None

    def cache_character(self, character_data):
        """Met en cache les données d'un personnage"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        # Convertir les listes en JSON pour le stockage
        animeography_json = json.dumps(character_data.get('animeography', []))
        voice_actors_json = json.dumps(character_data.get('voices', []))
        # Gérer les images correctement
        images = character_data.get('images', {})
        image_url = None
        if images.get('jpg'):
            image_url = images['jpg'].get('image_url')
        cursor.execute('''
            INSERT OR REPLACE INTO character_cache 
            (character_id, name, name_kanji, about, image_url, favorites, animeography, voice_actors)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            character_data.get('mal_id'),
            character_data.get('name'),
            character_data.get('name_kanji'),
            character_data.get('about'),
            image_url,
            character_data.get('favorites'),
            animeography_json,
            voice_actors_json
        ))
        conn.commit()
        conn.close()

    def get_cached_character(self, character_id):
        """Récupère un personnage depuis le cache"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM character_cache WHERE character_id = ?
        ''', (character_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            # Reconstruire l'objet character à partir des données en cache
            return {
                'mal_id': row[0],
                'name': row[1],
                'name_kanji': row[2],
                'about': row[3],
                'images': {'jpg': {'image_url': row[4]}},
                'favorites': row[5],
                'animeography': json.loads(row[6]),
                'voices': json.loads(row[7])
            }
        return None

# Initialisation de la base de données
db = AnimeDatabase()

# ──────────────────────────
# Système d'Achievements
# ──────────────────────────
ACHIEVEMENTS = {
    'anime_explorer': {
        'name': '🏆 Explorateur d\'Animes',
        'description': 'Consulter 50 animes différents',
        'condition': lambda user_id: len(db.get_favorites(user_id)) + len(db.get_watchlist(user_id)) >= 50
    },
    'genre_master': {
        'name': '🎭 Maître des Genres',
        'description': 'Explorer 10 genres différents',
        'condition': lambda user_id: check_genre_variety(user_id) >= 10
    },
    'season_watcher': {
        'name': '📅 Observateur de Saisons',
        'description': 'Consulter des animes de 4 saisons différentes',
        'condition': lambda user_id: check_season_variety(user_id) >= 4
    },
    'anime_lover': {
        'name': '❤️ Amoureux d\'Animes',
        'description': 'Ajouter 20 animes aux favoris',
        'condition': lambda user_id: len(db.get_favorites(user_id)) >= 20
    },
    'completionist': {
        'name': '✅ Completionniste',
        'description': 'Marquer 10 animes comme complétés',
        'condition': lambda user_id: len([item for item in db.get_watchlist(user_id) if item['status'] == 'completed']) >= 10
    }
}

def check_genre_variety(user_id):
    """Vérifie la variété des genres explorés par l'utilisateur"""
    favorites = db.get_favorites(user_id)
    watchlist = db.get_watchlist(user_id)
    all_anime_ids = set(favorites)
    for item in watchlist:
        all_anime_ids.add(item['anime_id'])
    genres = set()
    for anime_id in all_anime_ids:
        anime = db.get_cached_anime(anime_id) or get_anime_by_id(anime_id)
        if anime and 'genres' in anime:
            for genre in anime['genres']:
                genres.add(genre['name'])
    return len(genres)

def check_season_variety(user_id):
    """Vérifie la variété des saisons explorées par l'utilisateur"""
    favorites = db.get_favorites(user_id)
    watchlist = db.get_watchlist(user_id)
    all_anime_ids = set(favorites)
    for item in watchlist:
        all_anime_ids.add(item['anime_id'])
    seasons = set()
    for anime_id in all_anime_ids:
        anime = db.get_cached_anime(anime_id) or get_anime_by_id(anime_id)
        if anime and 'year' in anime and 'season' in anime:
            seasons.add(f"{anime['year']}-{anime.get('season', '')}")
    return len(seasons)

def check_achievements(user_id):
    """Vérifie et attribue les achievements à un utilisateur"""
    new_achievements = []
    for achievement_id, achievement in ACHIEVEMENTS.items():
        if achievement['condition'](user_id):
            if db.add_achievement(user_id, achievement_id, achievement['name']):
                new_achievements.append(achievement['name'])
    return new_achievements

# ──────────────────────────
# Système de Recommandations Personnalisées
# ──────────────────────────
def get_personal_recommendations(user_id, limit=5):
    """Génère des recommandations personnalisées basées sur les préférences de l'utilisateur"""
    favorites = db.get_favorites(user_id)
    watchlist = db.get_watchlist(user_id)
    if not favorites and not watchlist:
        return get_top_anime(limit=limit)
    # Analyser les genres préférés
    genre_counter = {}
    all_anime_ids = set(favorites)
    for item in watchlist:
        all_anime_ids.add(item['anime_id'])
    for anime_id in all_anime_ids:
        anime = db.get_cached_anime(anime_id) or get_anime_by_id(anime_id)
        if anime and 'genres' in anime:
            for genre in anime['genres']:
                genre_name = genre['name']
                genre_counter[genre_name] = genre_counter.get(genre_name, 0) + 1
    # Obtenir les genres les plus populaires
    top_genres = sorted(genre_counter.items(), key=lambda x: x[1], reverse=True)[:3]
    # Rechercher des animes similaires
    recommendations = []
    for genre, _ in top_genres:
        genre_recommendations = search_anime_by_genre(genre, limit=limit)
        for rec in genre_recommendations:
            if rec['mal_id'] not in all_anime_ids and rec['mal_id'] not in [r['mal_id'] for r in recommendations]:
                recommendations.append(rec)
                if len(recommendations) >= limit:
                    break
        if len(recommendations) >= limit:
            break
    # Compléter avec des animes populaires si nécessaire
    if len(recommendations) < limit:
        top_anime = get_top_anime(limit=limit * 2)
        for anime in top_anime:
            if anime['mal_id'] not in all_anime_ids and anime['mal_id'] not in [r['mal_id'] for r in recommendations]:
                recommendations.append(anime)
                if len(recommendations) >= limit:
                    break
    return recommendations[:limit]

def search_anime_by_genre(genre, limit=10):
    """Recherche des animes par genre"""
    url = f"https://api.jikan.moe/v4/anime?genres={genre}&limit={limit}"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            data = r.json()
            return data.get("data") or []
        logger.error(f"Erreur API Jikan (genre search): {r.status_code}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Erreur de connexion (genre search): {e}")
    return []

# ──────────────────────────
# Utilitaires de texte
# ──────────────────────────
def decode_html_entities(text: str) -> str:
    """Décoder &amp;, &#x27;, etc."""
    if not text:
        return ""
    return html.unescape(text)

def escape_html(text: str) -> str:
    """Échapper pour parse_mode=HTML ( &, <, >, " )"""
    if text is None:
        return ""
    return html.escape(text, quote=True)

def truncate(s: str, limit: int) -> str:
    s = s or ""
    return (s[: limit - 3] + "...") if len(s) > limit else s

def create_slug(title: str) -> str:
    """Crée un slug à partir d'un titre d'anime"""
    # Convertir en minuscules
    slug = title.lower()
    # Remplacer les espaces par des tirets
    slug = re.sub(r'\s+', '-', slug)
    # Supprimer les caractères non alphanumériques (sauf les tirets)
    slug = re.sub(r'[^a-z0-9\-]', '', slug)
    # Supprimer les tirets multiples
    slug = re.sub(r'\-+', '-', slug)
    # Supprimer les tirets en début et fin
    slug = slug.strip('-')
    return slug

# ──────────────────────────
# Appels API Jikan
# ──────────────────────────
def search_anime(query, limit=10):
    url = f"https://api.jikan.moe/v4/anime?q={query}&limit={limit}"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            data = r.json()
            anime_list = data.get("data") or []
            # Mettre en cache les résultats
            for anime in anime_list:
                db.cache_anime(anime)
            return anime_list
        logger.error(f"Erreur API Jikan: {r.status_code}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Erreur de connexion: {e}")
    return None

def get_anime_by_id(anime_id):
    # Vérifier d'abord le cache
    cached_anime = db.get_cached_anime(anime_id)
    if cached_anime:
        return cached_anime
    url = f"https://api.jikan.moe/v4/anime/{anime_id}"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            anime = r.json().get("data")
            if anime:
                db.cache_anime(anime)
            return anime
    except requests.exceptions.RequestException as e:
        logger.error(f"Erreur de connexion: {e}")
    return None

def get_anime_by_season(year, season):
    url = f"https://api.jikan.moe/v4/seasons/{year}/{season}"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            anime_list = (r.json().get("data") or [])[:20]
            # Mettre en cache les résultats
            for anime in anime_list:
                db.cache_anime(anime)
            return anime_list
        logger.error(f"Erreur API Jikan: {r.status_code}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Erreur de connexion: {e}")
    return None

def search_character(query, limit=10):
    url = f"https://api.jikan.moe/v4/characters?q={query}&limit={limit}"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            data = r.json()
            character_list = data.get("data") or []
            # Mettre en cache les résultats
            for character in character_list:
                db.cache_character(character)
            return character_list
        logger.error(f"Erreur API Jikan: {r.status_code}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Erreur de connexion: {e}")
    return None

def get_character_by_id(character_id):
    """Récupère les détails complets d'un personnage par son ID"""
    # Vérifier d'abord le cache
    cached_character = db.get_cached_character(character_id)
    if cached_character:
        return cached_character
    url = f"https://api.jikan.moe/v4/characters/{character_id}/full"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            character = r.json().get("data")
            if character:
                db.cache_character(character)
            return character
        logger.error(f"Erreur API Jikan (character): {r.status_code}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Erreur de connexion (character): {e}")
    return None

def get_anime_characters(anime_id):
    """Récupère tous les personnages d'un anime"""
    url = f"https://api.jikan.moe/v4/anime/{anime_id}/characters"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            data = r.json()
            return data.get("data") or []
        logger.error(f"Erreur API Jikan (anime characters): {r.status_code}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Erreur de connexion (anime characters): {e}")
    return []

def get_anime_recommendations(genres, exclude_id, limit=5):
    # Correction : utiliser les noms de genres pour la recherche
    # Jikan ne permet pas de filtrer directement par genre ID
    # On utilise une recherche par mots-clés ou on fait une requête par genre
    # Pour simplifier, on ne fait pas de recherche basée sur les genres
    # On renvoie une liste vide pour éviter KeyError
    logger.warning(f"Recommandations par genre non implémentées correctement (mal_id manquant dans {genres})")
    return []

def get_top_anime(filter_type="all", page=1, limit=10):
    url = f"https://api.jikan.moe/v4/top/anime?filter={filter_type}&page={page}&limit={limit}"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            data = r.json()
            anime_list = data.get("data") or []
            # Mettre en cache les résultats
            for anime in anime_list:
                db.cache_anime(anime)
            return anime_list, data.get("pagination", {}).get("last_visible_page", 1)
        logger.error(f"Erreur API Jikan (top): {r.status_code}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Erreur de connexion (top): {e}")
    return [], 1

def get_random_anime():
    url = "https://api.jikan.moe/v4/random/anime"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            anime = r.json().get("data")
            if anime:
                db.cache_anime(anime)
            return anime
        logger.error(f"Erreur API Jikan (random): {r.status_code}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Erreur de connexion (random): {e}")
    return None

def get_schedule(day=None):
    if day:
        url = f"https://api.jikan.moe/v4/schedules?filter={day}"
    else:
        url = "https://api.jikan.moe/v4/schedules"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            anime_list = r.json().get("data") or []
            # Mettre en cache les résultats
            for anime in anime_list:
                db.cache_anime(anime)
            return anime_list
        logger.error(f"Erreur API Jikan (schedule): {r.status_code}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Erreur de connexion (schedule): {e}")
    return []

# ──────────────────────────
# Intégration Nautiljon
# ──────────────────────────
def search_nautiljon(query, search_type="anime"):
    """Recherche sur Nautiljon et retourne les résultats"""
    if query in nautiljon_cache:
        return nautiljon_cache[query]
    params = {
        'mot': query,
        'type': search_type
    }
    try:
        url = f"{NAUTILJON_SEARCH_URL}?{urlencode(params)}"
        response = requests.get(url, timeout=10, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        if response.status_code == 200:
            # Extraction basique des résultats (simplifié)
            results = []
            pattern = r'<a href="(/[\w/-]+)" title="([^"]+)">'
            matches = re.findall(pattern, response.text)
            for href, title in matches[:5]:  # Limiter à 5 résultats
                if "/mangas/" in href or "/anime/" in href or "/personnages/" in href:
                    results.append({
                        'title': decode_html_entities(title),
                        'url': f"{NAUTILJON_BASE_URL}{href}"
                    })
            nautiljon_cache[query] = results
            return results
    except Exception as e:
        logger.error(f"Erreur recherche Nautiljon: {e}")
    return []

def get_nautiljon_character_info(character_name):
    """Récupère les informations détaillées d'un personnage sur Nautiljon"""
    results = search_nautiljon(character_name, "personnages")
    if results:
        # Prendre le premier résultat
        character_url = results[0]['url']
        try:
            response = requests.get(character_url, timeout=10, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            })
            if response.status_code == 200:
                # Extraction des informations de base (simplifié)
                html_content = response.text
                # Extraction de la description
                description_match = re.search(r'<div class="description[^>]*>(.*?)</div>', html_content, re.DOTALL)
                description = description_match.group(1).strip() if description_match else "Aucune description disponible"
                # Nettoyage du HTML
                description = re.sub(r'<[^>]+>', '', description)
                description = re.sub(r'\s+', ' ', description).strip()
                return {
                    'name': results[0]['title'],
                    'url': character_url,
                    'description': description[:1000] + "..." if len(description) > 1000 else description
                }
        except Exception as e:
            logger.error(f"Erreur chargement personnage Nautiljon: {e}")
    return None

# ──────────────────────────
# Vérification des liens de streaming
# ──────────────────────────
async def check_streaming_availability(anime_title):
    """Vérifie la disponibilité sur les sites de streaming"""
    results = {}
    slug = create_slug(anime_title)
    for site in STREAMING_SITES:
        try:
            # Essayer d'abord avec l'URL directe
            if "anime_url" in site:
                if "{slug}" in site["anime_url"]:
                    test_url = site["anime_url"].format(slug=slug)
                else:
                    # Pour Anime-Ultime qui utilise un ID, on utilise la recherche
                    test_url = site["search_url"].format(query=quote(anime_title))
                # Faire une requête HEAD pour vérifier si la page existe
                response = requests.head(test_url, timeout=5, allow_redirects=True)
                if response.status_code == 200:
                    results[site["name"]] = test_url
                    continue
            # Fallback sur la recherche
            search_url = site["search_url"].format(query=quote(anime_title))
            results[site["name"]] = search_url
        except requests.exceptions.RequestException:
            # En cas d'erreur, utiliser l'URL de recherche
            search_url = site["search_url"].format(query=quote(anime_title))
            results[site["name"]] = search_url
    return results

# ──────────────────────────
# Formatage (HTML)
# ──────────────────────────
def format_anime_basic_info(anime, user_id=None):
    titre = escape_html(decode_html_entities(anime.get("title", "Titre inconnu")))
    titre_jp = escape_html(decode_html_entities(anime.get("title_japanese", ""))) or "N/A"
    score = escape_html(str(anime.get("score", "N/A")))
    episodes = escape_html(str(anime.get("episodes", "Inconnu")))
    status = escape_html(decode_html_entities(anime.get("status", "Inconnu")))
    year = escape_html(str(anime.get("year", "N/A")))
    # Vérifier si l'anime est dans les favoris
    is_fav = db.is_favorite(user_id, anime["mal_id"]) if user_id else False
    fav_status = "❤️" if is_fav else "🤍"
    caption = (
        f"🎌 <b>{titre}</b>{f' ({titre_jp})' if titre_jp != 'N/A' else ''}\n"
        f"⭐ <b>Note</b> : {score}/10\n"
        f"📺 <b>Épisodes</b> : {episodes}\n"
        f"📊 <b>Statut</b> : {status}\n"
        f"📅 <b>Année</b> : {year}\n"
        f"👇 <b>Utilisez les boutons pour plus d'infos</b>"
    )
    # Limite caption Telegram: 1024
    return truncate(caption, 1024)

def format_synopsis(anime):
    titre = escape_html(decode_html_entities(anime.get("title", "Titre inconnu")))
    synopsis = decode_html_entities(anime.get("synopsis", "Pas de synopsis disponible"))
    try:
        if synopsis and synopsis != "Pas de synopsis disponible":
            synopsis_short = truncate(synopsis, 800)
            synopsis_fr = GoogleTranslator(source="auto", target="fr").translate(synopsis_short)
        else:
            synopsis_fr = synopsis
    except Exception as e:
        logger.error(f"Erreur de traduction: {e}")
        synopsis_fr = synopsis
    synopsis_fr = escape_html(synopsis_fr)
    return f"📝 <b>Synopsis de {titre}</b> :\n{synopsis_fr}"

def format_details(anime):
    titre = escape_html(decode_html_entities(anime.get("title", "Titre inconnu")))
    rating = escape_html(decode_html_entities(anime.get("rating", "N/A")))
    duration = escape_html(anime.get("duration", "N/A"))
    source = escape_html(decode_html_entities(anime.get("source", "N/A")))
    genres = ", ".join(escape_html(decode_html_entities(g["name"])) for g in anime.get("genres", []))
    return (
        f"🔍 <b>Détails de {titre}</b> :\n"
        f"🎭 <b>Genres</b> : {genres or 'N/A'}\n"
        f"⏱️ <b>Durée par épisode</b> : {duration}\n"
        f"📚 <b>Source</b> : {source}\n"
        f"🔞 <b>Classification</b> : {rating}"
    )

def format_studio_info(anime):
    titre = escape_html(decode_html_entities(anime.get("title", "Titre inconnu")))
    studios = [escape_html(decode_html_entities(s["name"])) for s in anime.get("studios", [])]
    producers = [escape_html(decode_html_entities(p["name"])) for p in anime.get("producers", [])]
    studio_text = ", ".join(studios) if studios else "Inconnu"
    producer_text = ", ".join(producers[:3]) if producers else "Inconnu"
    return (
        f"🏢 <b>Infos production de {titre}</b> :\n"
        f"🎬 <b>Studio(s)</b> : {studio_text}\n"
        f"👔 <b>Producteur(s)</b> : {producer_text}"
    )

def format_character_info(character, nautiljon_data=None):
    """Formatage amélioré des informations sur les personnages"""
    name = escape_html(decode_html_entities(character.get("name", "Nom inconnu")))
    name_kanji = escape_html(decode_html_entities(character.get("name_kanji", "")))
    about = decode_html_entities(character.get("about", "Pas d'informations disponibles"))
    # Récupérer les informations supplémentaires si disponibles
    nicknames = character.get("nicknames", [])
    favorites = character.get("favorites", 0)
    animeography = character.get("animeography", [])
    voice_actors = character.get("voices", []) if isinstance(character.get("voices"), list) else []
    # Utiliser les données Nautiljon si disponibles
    if nautiljon_data:
        about = nautiljon_data.get('description', about)
    # Traduire la description
    try:
        if about and about != "Pas d'informations disponibles":
            # Utiliser plus de texte pour une meilleure description
            about_to_translate = about[:1500]  # Augmenter la limite
            about_fr = GoogleTranslator(source="auto", target="fr").translate(about_to_translate)
        else:
            about_fr = about
    except Exception as e:
        logger.error(f"Erreur de traduction personnage: {e}")
        about_fr = about
    about_fr = escape_html(about_fr)
    # Construction du texte (limité à 1024 caractères pour Telegram)
    text = f"👤 <b>{name}</b>"
    if name_kanji:
        text += f" ({name_kanji})"
    if nicknames:
        text += f"\n🎭 <b>Surnoms</b>: {', '.join([escape_html(n) for n in nicknames])}"
    text += f"\n❤️ <b>Favoris</b>: {favorites}"
    if about_fr:
        # Limiter la description pour éviter les erreurs de longueur
        about_fr = truncate(about_fr, 800)
        text += f"\n📝 <b>Description</b>:\n{about_fr}"
    # Ajouter les anime principaux
    if animeography:
        main_anime = [a for a in animeography if a.get("role") == "Main"]
        if main_anime:
            text += f"\n📺 <b>Anime principal</b>: {escape_html(main_anime[0].get('name', 'Inconnu'))}"
    # Ajouter les doubleurs (seiyuu)
    if voice_actors:
        japanese_va = [va for va in voice_actors if va.get('language') == 'Japanese']
        if japanese_va:
            va_name = japanese_va[0].get('person', {}).get('name', 'Inconnu')
            text += f"\n🎙️ <b>Seiyuu</b>: {escape_html(va_name)}"
    # Ajouter le lien Nautiljon si disponible
    if nautiljon_data:
        text += f"\n🔗 <a href='{nautiljon_data['url']}'>Voir plus sur Nautiljon</a>"
    return truncate(text, 1024)  # S'assurer que le texte ne dépasse pas la limite

def format_anime_characters_list(anime_title, characters):
    """Formate la liste des personnages d'un anime"""
    title = escape_html(decode_html_entities(anime_title))
    text = f"👥 <b>Personnages de {title}</b>\n"
    # Séparer les personnages principaux et secondaires
    main_characters = [c for c in characters if c.get("role") == "Main"]
    supporting_characters = [c for c in characters if c.get("role") == "Supporting"]
    if main_characters:
        text += "🎯 <b>Personnages Principaux</b>:\n"
        for i, character in enumerate(main_characters[:10], 1):  # Limiter à 10
            name = escape_html(decode_html_entities(character.get("character", {}).get("name", "Inconnu")))
            text += f"{i}. {name}\n"
    if supporting_characters:
        text += "\n👥 <b>Personnages Secondaires</b>:\n"
        for i, character in enumerate(supporting_characters[:10], 1):  # Limiter à 10
            name = escape_html(decode_html_entities(character.get("character", {}).get("name", "Inconnu")))
            text += f"{i}. {name}\n"
    if len(main_characters) > 10 or len(supporting_characters) > 10:
        text += f"\n... et {max(0, len(main_characters) - 10) + max(0, len(supporting_characters) - 10)} autres personnages"
    return text

def format_streaming_links(anime, streaming_links):
    """Formate les liens de streaming pour l'anime"""
    titre = escape_html(decode_html_entities(anime.get("title", "Titre inconnu")))
    # Créer le texte avec les liens
    text = f"📺 <b>Regarder {titre}</b>:\n"
    text += "Voici où vous pourriez trouver cet anime:\n"
    for site_name, url in streaming_links.items():
        text += f"• <a href='{escape_html(url)}'>{escape_html(site_name)}</a>\n"
    text += "\n🔍 <i>Note: Ces liens mènent directement aux animes quand disponibles, sinon à des pages de recherche.</i>"
    return text

def format_top_anime_list(anime_list, filter_type, page, total_pages):
    """Formate la liste des top animes"""
    filter_names = {
        "all": "Tous les temps",
        "airing": "En cours de diffusion",
        "upcoming": "À venir",
        "tv": "Séries TV",
        "movie": "Films",
        "ova": "OVA",
        "special": "Spéciaux",
        "bypopularity": "Populaires",
        "favorite": "Favoris"
    }
    text = f"🏆 <b>Top Anime - {filter_names.get(filter_type, filter_type)}</b>\n"
    for i, anime in enumerate(anime_list, 1):
        title = escape_html(decode_html_entities(anime.get("title", "Titre inconnu")))
        score = escape_html(str(anime.get("score", "N/A")))
        text += f"{i}. {title} ⭐ {score}\n"
    text += f"\n📄 Page {page}/{total_pages}"
    return text

def format_schedule(schedule_list, day=None):
    """Formate le planning des sorties"""
    day_names = {
        "monday": "Lundi",
        "tuesday": "Mardi",
        "wednesday": "Mercredi",
        "thursday": "Jeudi",
        "friday": "Vendredi",
        "saturday": "Samedi",
        "sunday": "Dimanche",
        "other": "Autre",
        "unknown": "Inconnu"
    }
    if day:
        title = f"📅 <b>Sorties du {day_names.get(day, day)}</b>\n"
    else:
        title = "📅 <b>Sorties de la semaine</b>\n"
    if not schedule_list:
        return title + "Aucune sortie prévue pour cette période."
    text = title
    for anime in schedule_list[:10]:  # Limiter à 10 résultats
        title = escape_html(decode_html_entities(anime.get("title", "Titre inconnu")))
        score = escape_html(str(anime.get("score", "N/A")))
        text += f"• {title}"
        if score != "N/A":
            text += f" ⭐ {score}"
        text += "\n"
    if len(schedule_list) > 10:
        text += f"\n... et {len(schedule_list) - 10} autres"
    return text

def format_watchlist_status(status, score=None, progress=None, episodes=None):
    """Formate le statut de visionnage"""
    status_names = {
        "plan_to_watch": "📥 Prévoir de regarder",
        "watching": "👁️ En cours de visionnage",
        "completed": "✅ Terminé",
        "dropped": "❌ Abandonné"
    }
    text = status_names.get(status, status)
    if score is not None:
        text += f" ⭐ {score}/10"
    if progress is not None and episodes is not None:
        text += f" 📊 {progress}/{episodes} épisodes"
    elif progress is not None:
        text += f" 📊 {progress} épisodes"
    return text

def format_user_stats(user_id):
    """Formate les statistiques de l'utilisateur"""
    favorites = db.get_favorites(user_id)
    watchlist = db.get_watchlist(user_id)
    achievements = db.get_achievements(user_id)
    # Compter les animes par statut
    status_counts = {
        "plan_to_watch": 0,
        "watching": 0,
        "completed": 0,
        "dropped": 0
    }
    for item in watchlist:
        status_counts[item['status']] += 1
    total_animes = len(favorites) + sum(status_counts.values())
    text = f"📊 <b>Vos Statistiques Anime</b>\n"
    text += f"❤️ <b>Favoris</b>: {len(favorites)} animes\n"
    text += f"📥 <b>À regarder</b>: {status_counts['plan_to_watch']} animes\n"
    text += f"👁️ <b>En cours</b>: {status_counts['watching']} animes\n"
    text += f"✅ <b>Terminés</b>: {status_counts['completed']} animes\n"
    text += f"❌ <b>Abandonnés</b>: {status_counts['dropped']} animes\n"
    text += f"📈 <b>Total</b>: {total_animes} animes\n"
    text += f"🏆 <b>Achievements</b>: {len(achievements)} obtenus\n"
    # Afficher les 3 derniers achievements
    if achievements:
        text += "\n<b>Derniers achievements:</b>\n"
        for ach in achievements[:3]:
            text += f"• {ach['name']}\n"
    return text

# ──────────────────────────
# Claviers inline 
# ──────────────────────────
def create_anime_navigation_keyboard(anime_id, user_id=None):
    keyboard = [
        [
            InlineKeyboardButton("📝 Synopsis", callback_data=f"synopsis_{anime_id}"),
            InlineKeyboardButton("🔍 Détails", callback_data=f"details_{anime_id}"),
        ],
        [
            InlineKeyboardButton("🏢 Studio", callback_data=f"studio_{anime_id}"),
            InlineKeyboardButton("🎬 Trailer", callback_data=f"trailer_{anime_id}"),
        ],
        [
            InlineKeyboardButton("👥 Personnages", callback_data=f"anime_chars_{anime_id}"),
            InlineKeyboardButton("🎯 Similaires", callback_data=f"similar_{anime_id}"),
        ],
        [
            InlineKeyboardButton("📺 Streaming", callback_data=f"streaming_{anime_id}"),
        ],
    ]
    # Ajouter les boutons de liste personnelle si user_id est fourni
    if user_id:
        is_fav = db.is_favorite(user_id, anime_id)
        fav_text = "❤️ Retirer des Favoris" if is_fav else "🤍 Ajouter aux Favoris"
        keyboard.append([
            InlineKeyboardButton(fav_text, callback_data=f"fav_{anime_id}"),
            InlineKeyboardButton("📋 Listes", callback_data=f"lists_{anime_id}")
        ])
    return InlineKeyboardMarkup(keyboard)

def create_lists_keyboard(anime_id, user_id):
    """Crée un clavier pour gérer les listes personnelles"""
    watch_status = db.get_watch_status(user_id, anime_id)
    keyboard = [
        [
            InlineKeyboardButton("📥 À regarder", callback_data=f"watch_plan_{anime_id}"),
            InlineKeyboardButton("👁️ En cours", callback_data=f"watch_watch_{anime_id}"),
        ],
        [
            InlineKeyboardButton("✅ Terminé", callback_data=f"watch_comp_{anime_id}"),
            InlineKeyboardButton("❌ Abandonné", callback_data=f"watch_drop_{anime_id}"),
        ]
    ]
    if watch_status:
        keyboard.append([
            InlineKeyboardButton("📊 Modifier progression", callback_data=f"progress_{anime_id}")
        ])
    keyboard.append([
        InlineKeyboardButton("🔙 Retour", callback_data=f"anime_{anime_id}")
    ])
    return InlineKeyboardMarkup(keyboard)

def create_progress_keyboard(anime_id, current_progress=0, episodes=None):
    """Crée un clavier pour modifier la progression"""
    keyboard = []
    # Boutons pour augmenter/réduire la progression
    if episodes and current_progress < episodes:
        keyboard.append([
            InlineKeyboardButton("➖", callback_data=f"progress_{anime_id}_down"),
            InlineKeyboardButton(f"{current_progress}", callback_data="noop"),
            InlineKeyboardButton("➕", callback_data=f"progress_{anime_id}_up")
        ])
    # Bouton pour terminer tous les épisodes
    if episodes:
        keyboard.append([
            InlineKeyboardButton(f"✅ Terminer ({episodes})", callback_data=f"progress_{anime_id}_{episodes}")
        ])
    keyboard.append([
        InlineKeyboardButton("🔙 Retour", callback_data=f"lists_{anime_id}")
    ])
    return InlineKeyboardMarkup(keyboard)

def create_characters_list_keyboard(characters, anime_id, page=0, items_per_page=10):
    """Crée un clavier pour la liste des personnages d'un anime"""
    keyboard = []
    start_idx = page * items_per_page
    end_idx = min(start_idx + items_per_page, len(characters))
    for i in range(start_idx, end_idx):
        character = characters[i]
        char_data = character.get("character", {})
        name = decode_html_entities(char_data.get("name", "Sans nom"))
        character_id = char_data.get("mal_id")
        if len(name) > 30:
            name = name[:27] + "..."
        role = character.get("role", "")
        if role == "Main":
            name = "🎯 " + name
        elif role == "Supporting":
            name = "👥 " + name
        keyboard.append([InlineKeyboardButton(name, callback_data=f"character_{character_id}")])
    # Ajouter la pagination si nécessaire
    total_pages = math.ceil(len(characters) / items_per_page)
    if total_pages > 1:
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton("⬅️", callback_data=f"chars_page_{anime_id}_{page-1}"))
        nav_buttons.append(InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="noop"))
        if page < total_pages - 1:
            nav_buttons.append(InlineKeyboardButton("➡️", callback_data=f"chars_page_{anime_id}_{page+1}"))
        keyboard.append(nav_buttons)
    # Ajouter le bouton retour
    keyboard.append([InlineKeyboardButton("🔙 Retour à l'anime", callback_data=f"anime_{anime_id}")])
    return InlineKeyboardMarkup(keyboard)

def create_search_pagination_keyboard(results, current_page=0, query="", search_type="anime"):
    keyboard = []
    items_per_page = 5
    total_pages = max(1, math.ceil(len(results) / items_per_page))
    start_idx = current_page * items_per_page
    end_idx = min(start_idx + items_per_page, len(results))
    for i in range(start_idx, end_idx):
        item = results[i]
        if search_type == "anime":
            title = decode_html_entities(item.get("title", "Sans titre"))
            item_id = item.get("mal_id")
            callback_prefix = "anime"
        else:
            title = decode_html_entities(item.get("name", "Sans nom"))
            item_id = item.get("mal_id")
            callback_prefix = "character"
        if len(title) > 35:
            title = title[:32] + "..."
        # (Les labels de boutons n'ont pas besoin d'échappement HTML)
        keyboard.append([InlineKeyboardButton(title, callback_data=f"{callback_prefix}_{item_id}")])
    if total_pages > 1:
        nav_row = []
        if current_page > 0:
            nav_row.append(InlineKeyboardButton("⬅️", callback_data=f"page_{search_type}_{query}_{current_page-1}"))
        nav_row.append(InlineKeyboardButton(f"{current_page + 1}/{total_pages}", callback_data="noop"))
        if current_page < total_pages - 1:
            nav_row.append(InlineKeyboardButton("➡️", callback_data=f"page_{search_type}_{query}_{current_page+1}"))
        keyboard.append(nav_row)
    return InlineKeyboardMarkup(keyboard)

def create_top_anime_keyboard(current_filter="all", current_page=1, total_pages=1):
    """Crée un clavier pour la navigation des top animes"""
    filter_buttons = [
        [
            InlineKeyboardButton("🎯 Tous", callback_data="top_all_1"),
            InlineKeyboardButton("📡 En cours", callback_data="top_airing_1"),
            InlineKeyboardButton("🔮 À venir", callback_data="top_upcoming_1"),
        ],
        [
            InlineKeyboardButton("📺 Séries", callback_data="top_tv_1"),
            InlineKeyboardButton("🎬 Films", callback_data="top_movie_1"),
            InlineKeyboardButton("💎 OVA", callback_data="top_ova_1"),
        ],
        [
            InlineKeyboardButton("⭐ Populaires", callback_data="top_bypopularity_1"),
            InlineKeyboardButton("❤️ Favoris", callback_data="top_favorite_1"),
        ]
    ]
    # Navigation des pages
    navigation_buttons = []
    if current_page > 1:
        navigation_buttons.append(InlineKeyboardButton("⬅️", callback_data=f"top_{current_filter}_{current_page-1}"))
    navigation_buttons.append(InlineKeyboardButton(f"{current_page}/{total_pages}", callback_data="noop"))
    if current_page < total_pages:
        navigation_buttons.append(InlineKeyboardButton("➡️", callback_data=f"top_{current_filter}_{current_page+1}"))
    if navigation_buttons:
        filter_buttons.append(navigation_buttons)
    return InlineKeyboardMarkup(filter_buttons)

def create_schedule_keyboard():
    """Crée un clavier pour la navigation du planning"""
    days = [
        [
            InlineKeyboardButton("📅 Aujourd'hui", callback_data="schedule_today"),
            InlineKeyboardButton("📅 Semaine", callback_data="schedule_week"),
        ],
        [
            InlineKeyboardButton("🗓️ Lundi", callback_data="schedule_monday"),
            InlineKeyboardButton("🗓️ Mardi", callback_data="schedule_tuesday"),
            InlineKeyboardButton("🗓️ Mercredi", callback_data="schedule_wednesday"),
        ],
        [
            InlineKeyboardButton("🗓️ Jeudi", callback_data="schedule_thursday"),
            InlineKeyboardButton("🗓️ Vendredi", callback_data="schedule_friday"),
            InlineKeyboardButton("🗓️ Samedi", callback_data="schedule_saturday"),
        ],
        [
            InlineKeyboardButton("🗓️ Dimanche", callback_data="schedule_sunday"),
        ]
    ]
    return InlineKeyboardMarkup(days)

def create_profile_keyboard():
    """Crée un clavier pour le profil utilisateur"""
    keyboard = [
        [
            InlineKeyboardButton("❤️ Favoris", callback_data="profile_favorites"),
            InlineKeyboardButton("📋 Ma Liste", callback_data="profile_watchlist"),
        ],
        [
            InlineKeyboardButton("📊 Statistiques", callback_data="profile_stats"),
            InlineKeyboardButton("🏆 Achievements", callback_data="profile_achievements"),
        ],
        [
            InlineKeyboardButton("🎯 Recommandations", callback_data="profile_recommendations"),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def create_watchlist_keyboard():
    """Crée un clavier pour naviguer dans la watchlist"""
    keyboard = [
        [
            InlineKeyboardButton("📥 À regarder", callback_data="watchlist_plan"),
            InlineKeyboardButton("👁️ En cours", callback_data="watchlist_watch"),
        ],
        [
            InlineKeyboardButton("✅ Terminés", callback_data="watchlist_comp"),
            InlineKeyboardButton("❌ Abandonnés", callback_data="watchlist_drop"),
        ],
        [
            InlineKeyboardButton("🔙 Retour", callback_data="profile_back"),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

# ──────────────────────────
# Claviers inline pour les sous-pages
# ──────────────────────────
def create_back_button_keyboard(anime_id):
    """Crée un clavier avec uniquement le bouton Retour"""
    keyboard = [
        [InlineKeyboardButton("🔙 Retour à l'anime", callback_data=f"anime_{anime_id}")]
    ]
    return InlineKeyboardMarkup(keyboard)

def create_similar_animes_keyboard(similar_animes, original_anime_id):
    """Crée un clavier pour les animes similaires avec bouton retour"""
    keyboard = []
    for anime in similar_animes:
        title = decode_html_entities(anime.get("title", "Sans titre"))
        if len(title) > 35:
            title = title[:32] + "..."
        keyboard.append([InlineKeyboardButton(title, callback_data=f"anime_{anime['mal_id']}")])
    # Ajouter le bouton retour
    keyboard.append([InlineKeyboardButton("🔙 Retour", callback_data=f"anime_{original_anime_id}")])
    return InlineKeyboardMarkup(keyboard)

# ──────────────────────────
# Commandes
# ──────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    db.add_user(user.id, user.username, user.first_name, user.last_name, user.language_code)
    keyboard = [
        [InlineKeyboardButton("🔍 Rechercher un anime", switch_inline_query_current_chat="")],
        [InlineKeyboardButton("👤 Mon Profil", callback_data="profile_main")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    welcome_text = (
        "👋 Bonjour ! Je suis votre assistant pour découvrir des animes.\n"
        "✨ <b>Fonctionnalités :</b>\n"
        "• 🔍 Recherche d'animes avec navigation interactive\n"
        "• 📝 Synopsis détaillés et traduits\n"
        "• 🎬 Liens vers les trailers officiels\n"
        "• 🎯 Recommandations d'animes similaires\n"
        "• 📅 Recherche par saison\n"
        "• 👤 Recherche de personnages\n"
        "• 🏆 Top animes\n"
        "• 🎲 Anime aléatoire\n"
        "• 📅 Planning des sorties\n"
        "• 👥 Fonctionne dans les groupes et en privé\n"
        "💡 <b>Nouvelles fonctionnalités :</b>\n"
        "• ❤️ Système de favoris et listes personnalisées\n"
        "• 📊 Statistiques personnelles\n"
        "• 🏆 Système d'achievements\n"
        "• 🎯 Recommandations personnalisées\n"
        "💡 <b>Commandes disponibles :</b>\n"
        "• Tapez le nom d'un anime pour le rechercher\n"
        "• <code>/saison <année> <saison></code> (ex : <code>/saison 2023 fall</code>)\n"
        "• <code>/personnage <nom></code> (ex : <code>/personnage Naruto</code>)\n"
        "• <code>/top</code> - Liste des meilleurs animes\n"
        "• <code>/random</code> - Anime aléatoire\n"
        "• <code>/planning</code> - Planning des sorties\n"
        "• <code>/profil</code> - Votre profil utilisateur\n"
        "• <code>/anime <nom></code> ou <code>/recherche <nom></code>"
    )
    await update.message.reply_text(welcome_text, parse_mode="HTML", reply_markup=reply_markup)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "🤖 <b>Aide - Bot Anime</b>\n"
        "🔍 <b>Recherche d'animes :</b>\n"
        "• Tapez le nom d'un anime\n"
        "• <code>/recherche <nom></code> ou <code>/anime <nom></code>\n"
        "📅 <b>Recherche par saison :</b>\n"
        "• <code>/saison <année> <saison></code> (spring, summer, fall, winter)\n"
        "• ex : <code>/saison 2023 fall</code>\n"
        "👤 <b>Recherche de personnages :</b>\n"
        "• <code>/personnage <nom></code>\n"
        "• ex : <code>/personnage Naruto</code>\n"
        "🏆 <b>Top animes :</b>\n"
        "• <code>/top</code> - Liste des meilleurs animes\n"
        "🎲 <b>Anime aléatoire :</b>\n"
        "• <code>/random</code> - Découvrir un anime au hasard\n"
        "📅 <b>Planning des sorties :</b>\n"
        "• <code>/planning</code> - Voir les sorties de la semaine\n"
        "👤 <b>Profil utilisateur :</b>\n"
        "• <code>/profil</code> - Gérer vos listes et voir vos stats\n"
        "🎯 <b>Navigation interactive :</b>\n"
        "• Boutons : Synopsis, Détails, Studio, Trailer, Personnages, Similaires, Streaming\n"
        "• Nouveau : Favoris, Listes de visionnage, Progression\n"
        "👥 <b>Groupes :</b>\n"
        "• Mentionne-moi puis écris le nom de l'anime"
    )
    await update.message.reply_text(help_text, parse_mode="HTML")

async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Affiche le profil de l'utilisateur"""
    user_id = update.message.from_user.id
    keyboard = create_profile_keyboard()
    # Vérifier les achievements
    new_achievements = check_achievements(user_id)
    text = "👤 <b>Votre Profil Anime</b>\n"
    text += "Gérez vos listes personnelles, consultez vos statistiques et découvrez vos achievements!\n"
    if new_achievements:
        text += "🎉 <b>Nouveaux achievements débloqués!</b>\n"
        for achievement in new_achievements:
            text += f"• {achievement}\n"
        text += "\n"
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=keyboard)

# ──────────────────────────
# Nouvelles commandes
# ──────────────────────────
async def season_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text(
            "❌ Format incorrect. Utilisez : <code>/saison <année> <saison></code>\n"
            "Saisons : <code>spring</code>, <code>summer</code>, <code>fall</code>, <code>winter</code>\n"
            "Exemple : <code>/saison 2023 fall</code>",
            parse_mode="HTML",
        )
        return
    year = context.args[0]
    season = context.args[1].lower()
    valid_seasons = ["spring", "summer", "fall", "winter"]
    if season not in valid_seasons:
        await update.message.reply_text(
            f"❌ Saison invalide. Utilisez : {', '.join(valid_seasons)}", parse_mode="HTML"
        )
        return
    await update.message.reply_chat_action(action="typing")
    results = get_anime_by_season(year, season)
    if not results:
        await update.message.reply_text(f"❌ Aucun anime trouvé pour {season} {year}.", parse_mode="HTML")
        return
    context.user_data[f"season_results_{year}_{season}"] = results
    season_names = {"spring": "Printemps", "summer": "Été", "fall": "Automne", "winter": "Hiver"}
    keyboard = create_search_pagination_keyboard(results, 0, f"{year}_{season}", "anime")
    await update.message.reply_text(
        f"📅 <b>Animes de {season_names[season]} {escape_html(str(year))}</b>\n"
        f"Trouvé {len(results)} anime(s). Sélectionnez celui qui vous intéresse :",
        parse_mode="HTML",
        reply_markup=keyboard,
    )

async def character_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "❌ Veuillez spécifier un nom de personnage. Exemple : <code>/personnage Naruto</code>",
            parse_mode="HTML",
        )
        return
    query = " ".join(context.args)
    await update.message.reply_chat_action(action="typing")
    results = search_character(query)
    if not results:
        await update.message.reply_text(f"❌ Aucun personnage trouvé pour « {escape_html(query)} ».", parse_mode="HTML")
        return
    context.user_data[f"character_results_{query}"] = results
    if len(results) == 1:
        await display_character_info(update, results[0])
    else:
        keyboard = create_search_pagination_keyboard(results, 0, query, "character")
        await update.message.reply_text(
            f"👤 Personnages trouvés pour « {escape_html(query)} » :\nSélectionnez celui qui vous intéresse :",
            parse_mode="HTML",
            reply_markup=keyboard,
        )

async def top_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Affiche les top animes avec filtres"""
    await update.message.reply_chat_action(action="typing")
    # Récupérer les top animes (par défault: tous)
    anime_list, total_pages = get_top_anime("all", 1)
    if not anime_list:
        await update.message.reply_text("❌ Impossible de charger les top animes.", parse_mode="HTML")
        return
    text = format_top_anime_list(anime_list, "all", 1, total_pages)
    keyboard = create_top_anime_keyboard("all", 1, total_pages)
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=keyboard)

async def random_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Affiche un anime aléatoire"""
    await update.message.reply_chat_action(action="typing")
    anime = get_random_anime()
    if not anime:
        await update.message.reply_text("❌ Impossible de charger un anime aléatoire.", parse_mode="HTML")
        return
    await display_anime_with_navigation(update, anime)

async def planning_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Affiche le planning des sorties"""
    await update.message.reply_chat_action(action="typing")
    # Déterminer le jour actuel si non spécifié
    day = context.args[0].lower() if context.args else None
    day_names = {
        "monday": "lundi", "tuesday": "mardi", "wednesday": "mercredi",
        "thursday": "jeudi", "friday": "vendredi", "saturday": "samedi",
        "sunday": "dimanche"
    }
    # Si "today" est demandé, déterminer le jour actuel
    if day == "today":
        today = datetime.now().strftime("%A").lower()
        day = today
    schedule = get_schedule(day)
    text = format_schedule(schedule, day)
    keyboard = create_schedule_keyboard()
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=keyboard)

# ──────────────────────────
# Affichages
# ──────────────────────────
async def display_character_info(update_or_query, character):
    # Récupérer les données Nautiljon pour enrichir la description
    character_name = character.get("name", "")
    nautiljon_data = get_nautiljon_character_info(character_name)
    info_text = format_character_info(character, nautiljon_data)
    # Gérer correctement l'URL de l'image
    images = character.get("images", {})
    image_url = None
    if images.get('jpg'):
        image_url = images['jpg'].get('image_url')
    if hasattr(update_or_query, "callback_query") and update_or_query.callback_query:
        message = update_or_query.callback_query.message
    elif hasattr(update_or_query, "message") and not hasattr(update_or_query, "callback_query"):
        message = update_or_query.message
    else:
        message = update_or_query.message
    if image_url:
        await message.reply_photo(photo=image_url, caption=info_text, parse_mode="HTML")
    else:
        await message.reply_text(info_text, parse_mode="HTML")

async def display_anime_with_navigation(update_or_query, anime, edit_message=False):
    user_id = None
    if hasattr(update_or_query, 'callback_query') and update_or_query.callback_query:
        user_id = update_or_query.callback_query.from_user.id
    elif hasattr(update_or_query, 'message') and update_or_query.message:
        user_id = update_or_query.message.from_user.id
    # Gérer correctement l'URL de l'image
    images = anime.get("images", {})
    image_url = None
    if images.get('jpg'):
        image_url = images['jpg'].get('large_image_url') or images['jpg'].get('image_url')
    caption = format_anime_basic_info(anime, user_id)
    keyboard = create_anime_navigation_keyboard(anime["mal_id"], user_id)
    if hasattr(update_or_query, "callback_query") and update_or_query.callback_query:
        query = update_or_query.callback_query
        message = query.message
    elif hasattr(update_or_query, "message") and not hasattr(update_or_query, "callback_query"):
        message = update_or_query.message
        query = None
    else:
        query = update_or_query
        message = query.message
    try:
        if edit_message and query:
            # En cas d'édition, on renvoie un nouveau message si l'API refuse l'edit
            await query.edit_message_caption(caption=caption, parse_mode="HTML", reply_markup=keyboard)
        else:
            if image_url:
                await message.reply_photo(photo=image_url, caption=caption, parse_mode="HTML", reply_markup=keyboard)
            else:
                await message.reply_text(caption, parse_mode="HTML", reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Erreur lors de l'affichage de l'anime: {e}")
        if image_url:
            await message.reply_photo(photo=image_url, caption=caption, parse_mode="HTML", reply_markup=keyboard)
        else:
            await message.reply_text(caption, parse_mode="HTML", reply_markup=keyboard)

# ──────────────────────────
# Recherche & messages
# ──────────────────────────
async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "❌ Veuillez spécifier un anime. Exemple : <code>/recherche One Piece</code>", parse_mode="HTML"
        )
        return
    query = " ".join(context.args)
    await perform_search(update, query, context)

async def anime_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "❌ Veuillez spécifier un anime. Exemple : <code>/anime Attack on Titan</code>", parse_mode="HTML"
        )
        return
    query = " ".join(context.args)
    await perform_search(update, query, context)

async def perform_search(update: Update, query: str, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_chat_action(action="typing")
    results = search_anime(query)
    if not results:
        await update.message.reply_text("❌ Aucun anime trouvé. Essayez avec un autre nom.", parse_mode="HTML")
        return
    context.user_data[f"search_results_{query}"] = results
    if len(results) == 1:
        await display_anime_with_navigation(update, results[0])
    else:
        keyboard = create_search_pagination_keyboard(results, 0, query, "anime")
        await update.message.reply_text(
            f"🔍 {len(results)} animes trouvés pour « {escape_html(query)} » :\nSélectionnez celui qui vous intéresse :",
            parse_mode="HTML",
            reply_markup=keyboard,
        )

# ──────────────────────────
# Boutons inline
# ──────────────────────────
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id
    # Ajouter l'utilisateur à la base de données s'il n'existe pas
    db.add_user(user_id, query.from_user.username, query.from_user.first_name, 
                query.from_user.last_name, query.from_user.language_code)
    if data.startswith("page_"):
        parts = data.split("_")
        if len(parts) >= 4:
            search_type = parts[1]
            search_query = "_".join(parts[2:-1])
            page = int(parts[-1])
            if search_type == "anime":
                stored_key = f"search_results_{search_query}"
                if f"season_results_{search_query}" in context.user_data:
                    stored_key = f"season_results_{search_query}"
                results = context.user_data.get(stored_key, [])
                if results:
                    keyboard = create_search_pagination_keyboard(results, page, search_query, "anime")
                    await query.edit_message_reply_markup(reply_markup=keyboard)
            elif search_type == "character":
                stored_key = f"character_results_{search_query}"
                results = context.user_data.get(stored_key, [])
                if results:
                    keyboard = create_search_pagination_keyboard(results, page, search_query, "character")
                    await query.edit_message_reply_markup(reply_markup=keyboard)
    elif data.startswith("anime_"):
        anime_id = data.split("_")[1]
        anime = get_anime_by_id(anime_id)
        if anime:
            await display_anime_with_navigation(query, anime)
        else:
            await query.message.reply_text("❌ Erreur lors du chargement des détails de l'anime.", parse_mode="HTML")
    elif data.startswith("character_"):
        character_id = data.split("_")[1]
        for key, results in context.user_data.items():
            if key.startswith("character_results_"):
                character = next((c for c in results if c["mal_id"] == int(character_id)), None)
                if character:
                    await display_character_info(query, character)
                    return
        await query.message.reply_text("❌ Erreur lors du chargement des détails du personnage.", parse_mode="HTML")
    elif data.startswith("synopsis_"):
        anime_id = data.split("_")[1]
        anime = get_anime_by_id(anime_id)
        if anime:
            synopsis_text = format_synopsis(anime)
            reply_markup = create_back_button_keyboard(anime_id)
            await query.message.reply_text(synopsis_text, parse_mode="HTML", reply_markup=reply_markup)
        else:
            await query.message.reply_text("❌ Impossible de charger le synopsis.", parse_mode="HTML")
    elif data.startswith("details_"):
        anime_id = data.split("_")[1]
        anime = get_anime_by_id(anime_id)
        if anime:
            details_text = format_details(anime)
            reply_markup = create_back_button_keyboard(anime_id)
            await query.message.reply_text(details_text, parse_mode="HTML", reply_markup=reply_markup)
        else:
            await query.message.reply_text("❌ Impossible de charger les détails.", parse_mode="HTML")
    elif data.startswith("studio_"):
        anime_id = data.split("_")[1]
        anime = get_anime_by_id(anime_id)
        if anime:
            studio_text = format_studio_info(anime)
            reply_markup = create_back_button_keyboard(anime_id)
            await query.message.reply_text(studio_text, parse_mode="HTML", reply_markup=reply_markup)
        else:
            await query.message.reply_text("❌ Impossible de charger les infos studio.", parse_mode="HTML")
    elif data.startswith("trailer_"):
        anime_id = data.split("_")[1]
        anime = get_anime_by_id(anime_id)
        if anime:
            trailer_url = None
            if anime.get("trailer") and anime["trailer"].get("url"):
                trailer_url = anime["trailer"]["url"]
            if trailer_url:
                titre = escape_html(decode_html_entities(anime.get("title", "Cet anime")))
                reply_markup = create_back_button_keyboard(anime_id)
                await query.message.reply_text(
                    f"🎬 <b>Trailer de {titre}</b>:\n{escape_html(trailer_url)}", 
                    parse_mode="HTML", 
                    reply_markup=reply_markup
                )
            else:
                reply_markup = create_back_button_keyboard(anime_id)
                await query.message.reply_text(
                    "❌ Aucun trailer disponible pour cet anime.", 
                    parse_mode="HTML", 
                    reply_markup=reply_markup
                )
        else:
            await query.message.reply_text("❌ Impossible de charger le trailer.", parse_mode="HTML")
    elif data.startswith("similar_"):
        anime_id = int(data.split("_")[1])
        anime = get_anime_by_id(anime_id)
        # Correction : Vérifier que les genres sont accessibles
        if anime and anime.get("genres"):
            # Utiliser une fonction de recommandation simplifiée
            recs = get_anime_recommendations(anime["genres"], anime_id, 5)
            if recs:
                titre_original = escape_html(decode_html_entities(anime.get("title", "Cet anime")))
                reply_markup = create_similar_animes_keyboard(recs, anime_id)
                await query.message.reply_text(
                    f"🎯 <b>Animes similaires à {titre_original}</b>:\nBasé sur des genres proches :",
                    parse_mode="HTML",
                    reply_markup=reply_markup,
                )
            else:
                reply_markup = create_back_button_keyboard(anime_id)
                await query.message.reply_text(
                    "❌ Aucune recommandation trouvée.", 
                    parse_mode="HTML", 
                    reply_markup=reply_markup
                )
        else:
            await query.message.reply_text("❌ Impossible de charger les recommandations.", parse_mode="HTML")
    elif data.startswith("streaming_"):
        anime_id = data.split("_")[1]
        anime = get_anime_by_id(anime_id)
        if anime:
            # Vérifier la disponibilité sur les sites de streaming
            streaming_links = await check_streaming_availability(anime.get("title", ""))
            streaming_text = format_streaming_links(anime, streaming_links)
            # Créer un clavier avec des boutons de liens
            keyboard = []
            for site_name, url in streaming_links.items():
                keyboard.append([InlineKeyboardButton(site_name, url=url)])
            # Ajouter un bouton retour
            keyboard.append([InlineKeyboardButton("🔙 Retour", callback_data=f"anime_{anime_id}")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.reply_text(streaming_text, parse_mode="HTML", reply_markup=reply_markup)
        else:
            await query.message.reply_text("❌ Impossible de charger les liens de streaming.", parse_mode="HTML")
    elif data.startswith("top_"):
        # Gestion des top animes
        parts = data.split("_")
        if len(parts) >= 3:
            filter_type = parts[1]
            page = int(parts[2])
            anime_list, total_pages = get_top_anime(filter_type, page)
            if anime_list:
                text = format_top_anime_list(anime_list, filter_type, page, total_pages)
                keyboard = create_top_anime_keyboard(filter_type, page, total_pages)
                await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)
            else:
                await query.answer("❌ Impossible de charger les top animes.")
    elif data.startswith("schedule_"):
        # Gestion du planning
        day = data.split("_")[1]
        if day == "today":
            today = datetime.now().strftime("%A").lower()
            day = today
        elif day == "week":
            day = None
        schedule = get_schedule(day)
        text = format_schedule(schedule, day)
        keyboard = create_schedule_keyboard()
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)
    elif data.startswith("anime_chars_"):
        # Afficher les personnages d'un anime
        anime_id = data.split("_")[2]
        anime = get_anime_by_id(anime_id)
        if anime:
            characters = get_anime_characters(anime_id)
            if characters:
                # Stocker les personnages dans le contexte pour la pagination
                context.user_data[f"anime_chars_{anime_id}"] = characters
                anime_title = anime.get("title", "Cet anime")
                list_text = format_anime_characters_list(anime_title, characters)
                keyboard = create_characters_list_keyboard(characters, anime_id, 0)
                await query.message.reply_text(list_text, parse_mode="HTML", reply_markup=keyboard)
            else:
                await query.message.reply_text("❌ Aucun personnage trouvé pour cet anime.", parse_mode="HTML")
        else:
            await query.message.reply_text("❌ Impossible de charger les personnages.", parse_mode="HTML")
    elif data.startswith("chars_page_"):
        # Pagination pour la liste des personnages
        parts = data.split("_")
        anime_id = parts[3]
        page = int(parts[4])
        characters = context.user_data.get(f"anime_chars_{anime_id}", [])
        if characters:
            anime = get_anime_by_id(anime_id)
            anime_title = anime.get("title", "Cet anime") if anime else "Cet anime"
            list_text = format_anime_characters_list(anime_title, characters)
            keyboard = create_characters_list_keyboard(characters, anime_id, page)
            await query.edit_message_text(list_text, parse_mode="HTML", reply_markup=keyboard)
        else:
            await query.answer("❌ Données de personnages non disponibles.")
    elif data.startswith("character_"):
        # Afficher les détails d'un personnage (version améliorée)
        character_id = data.split("_")[1]
        character = get_character_by_id(character_id)
        if character:
            # Pour le bouton retour, on essaie de trouver l'anime d'origine
            anime_id = None
            for key in context.user_data:
                if key.startswith("anime_chars_"):
                    anime_id = key.split("_")[2]
                    break
            if anime_id:
                reply_markup = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Retour aux personnages", callback_data=f"anime_chars_{anime_id}")]
                ])
            else:
                reply_markup = None
            # Récupérer les données Nautiljon pour enrichir la description
            character_name = character.get("name", "")
            nautiljon_data = get_nautiljon_character_info(character_name)
            info_text = format_character_info(character, nautiljon_data)
            # Gérer correctement l'URL de l'image
            images = character.get("images", {})
            image_url = None
            if images.get('jpg'):
                image_url = images['jpg'].get('image_url')
            if image_url:
                await query.message.reply_photo(
                    photo=image_url, 
                    caption=info_text, 
                    parse_mode="HTML", 
                    reply_markup=reply_markup
                )
            else:
                await query.message.reply_text(info_text, parse_mode="HTML", reply_markup=reply_markup)
        else:
            await query.message.reply_text("❌ Erreur lors du chargement des détails du personnage.", parse_mode="HTML")
    # Gestion des favoris
    elif data.startswith("fav_"):
        anime_id = int(data.split("_")[1])
        if db.is_favorite(user_id, anime_id):
            db.remove_from_favorites(user_id, anime_id)
            await query.answer("❌ Retiré des favoris")
        else:
            db.add_to_favorites(user_id, anime_id)
            await query.answer("❤️ Ajouté aux favoris")
            # Vérifier les achievements
            new_achievements = check_achievements(user_id)
            if new_achievements:
                achievement_text = "🎉 <b>Nouveaux achievements débloqués!</b>\n"
                for achievement in new_achievements:
                    achievement_text += f"• {achievement}\n"
                await query.message.reply_text(achievement_text, parse_mode="HTML")
        # Mettre à jour le message
        anime = get_anime_by_id(anime_id)
        if anime:
            await display_anime_with_navigation(query, anime, edit_message=True)
    # Gestion des listes
    elif data.startswith("lists_"):
        anime_id = int(data.split("_")[1])
        keyboard = create_lists_keyboard(anime_id, user_id)
        await query.message.reply_text(
            "📋 <b>Gérer les listes</b>\nSélectionnez une option:",
            parse_mode="HTML",
            reply_markup=keyboard
        )
    # Gestion du statut de visionnage
    elif data.startswith("watch_"):
        parts = data.split("_")
        anime_id = int(parts[2])
        status = parts[1]
        status_map = {
            "plan": "plan_to_watch",
            "watch": "watching",
            "comp": "completed",
            "drop": "dropped"
        }
        db.update_watchlist(user_id, anime_id, status_map[status])
        status_names = {
            "plan_to_watch": "📥 À regarder",
            "watching": "👁️ En cours",
            "completed": "✅ Terminé",
            "dropped": "❌ Abandonné"
        }
        await query.answer(f"Ajouté à {status_names[status_map[status]]}")
        # Vérifier les achievements
        new_achievements = check_achievements(user_id)
        if new_achievements:
            achievement_text = "🎉 <b>Nouveaux achievements débloqués!</b>\n"
            for achievement in new_achievements:
                achievement_text += f"• {achievement}\n"
            await query.message.reply_text(achievement_text, parse_mode="HTML")
        # Revenir à l'anime
        anime = get_anime_by_id(anime_id)
        if anime:
            await display_anime_with_navigation(query, anime)
    # Gestion de la progression
    elif data.startswith("progress_"):
        parts = data.split("_")
        anime_id = int(parts[1])
        if len(parts) == 2:
            # Afficher le clavier de progression
            anime = get_anime_by_id(anime_id)
            watch_status = db.get_watch_status(user_id, anime_id)
            current_progress = watch_status['progress'] if watch_status else 0
            episodes = anime.get('episodes')
            keyboard = create_progress_keyboard(anime_id, current_progress, episodes)
            await query.message.reply_text(
                "📊 <b>Modifier la progression</b>\nUtilisez les boutons pour ajuster:",
                parse_mode="HTML",
                reply_markup=keyboard
            )
        else:
            # Modifier la progression
            action = parts[2]
            watch_status = db.get_watch_status(user_id, anime_id)
            current_status = watch_status['status'] if watch_status else 'watching'
            current_progress = watch_status['progress'] if watch_status else 0
            anime = get_anime_by_id(anime_id)
            episodes = anime.get('episodes')
            if action == "up":
                new_progress = min(current_progress + 1, episodes if episodes else current_progress + 1)
            elif action == "down":
                new_progress = max(current_progress - 1, 0)
            else:
                new_progress = int(action)  # Valeur spécifique
            db.update_watchlist(user_id, anime_id, current_status, progress=new_progress)
            # Si on a atteint tous les épisodes, marquer comme complété
            if episodes and new_progress >= episodes:
                db.update_watchlist(user_id, anime_id, "completed", progress=episodes)
                await query.answer(f"✅ Progression mise à jour: {new_progress}/{episodes} (Terminé)")
            else:
                await query.answer(f"📊 Progression mise à jour: {new_progress}/{episodes if episodes else '?'}")
            # Vérifier les achievements
            new_achievements = check_achievements(user_id)
            if new_achievements:
                achievement_text = "🎉 <b>Nouveaux achievements débloqués!</b>\n"
                for achievement in new_achievements:
                    achievement_text += f"• {achievement}\n"
                await query.message.reply_text(achievement_text, parse_mode="HTML")
            # Mettre à jour le clavier
            keyboard = create_progress_keyboard(anime_id, new_progress, episodes)
            try:
                await query.message.edit_reply_markup(reply_markup=keyboard)
            except:
                pass  # Ignorer les erreurs d'édition
    # Gestion du profil
    elif data == "profile_main":
        keyboard = create_profile_keyboard()
        await query.message.edit_text(
            "👤 <b>Votre Profil Anime</b>\nSélectionnez une option:",
            parse_mode="HTML",
            reply_markup=keyboard
        )
    elif data == "profile_favorites":
        favorites = db.get_favorites(user_id)
        if not favorites:
            await query.message.edit_text(
                "❤️ <b>Vos Favoris</b>\nVous n'avez aucun anime dans vos favoris.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Retour", callback_data="profile_main")]])
            )
            return
        text = "❤️ <b>Vos Favoris</b>\n"
        for i, anime_id in enumerate(favorites[:10], 1):  # Limiter à 10
            anime = get_anime_by_id(anime_id)
            if anime:
                title = escape_html(decode_html_entities(anime.get("title", "Titre inconnu")))
                text += f"{i}. {title}\n"
        if len(favorites) > 10:
            text += f"\n... et {len(favorites) - 10} autres"
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Retour", callback_data="profile_main")]])
        await query.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
    elif data == "profile_watchlist":
        keyboard = create_watchlist_keyboard()
        await query.message.edit_text(
            "📋 <b>Votre Liste de Visionnage</b>\nSélectionnez une catégorie:",
            parse_mode="HTML",
            reply_markup=keyboard
        )
    elif data.startswith("watchlist_"):
        status = data.split("_")[1]
        status_map = {
            "plan": "plan_to_watch",
            "watch": "watching",
            "comp": "completed",
            "drop": "dropped"
        }
        watchlist = db.get_watchlist(user_id, status_map[status])
        if not watchlist:
            status_names = {
                "plan_to_watch": "📥 À regarder",
                "watching": "👁️ En cours",
                "completed": "✅ Terminés",
                "dropped": "❌ Abandonnés"
            }
            await query.message.edit_text(
                f"{status_names[status_map[status]]}\nAucun anime dans cette catégorie.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Retour", callback_data="profile_watchlist")]])
            )
            return
        status_names = {
            "plan": "📥 À regarder",
            "watch": "👁️ En cours",
            "comp": "✅ Terminés",
            "drop": "❌ Abandonnés"
        }
        text = f"{status_names[status]}\n"
        for i, item in enumerate(watchlist[:10], 1):  # Limiter à 10
            anime = get_anime_by_id(item['anime_id'])
            if anime:
                title = escape_html(decode_html_entities(anime.get("title", "Titre inconnu")))
                text += f"{i}. {title}"
                if item.get('progress'):
                    text += f" ({item['progress']}/{anime.get('episodes', '?')})"
                if item.get('score'):
                    text += f" ⭐ {item['score']}"
                text += "\n"
        if len(watchlist) > 10:
            text += f"\n... et {len(watchlist) - 10} autres"
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Retour", callback_data="profile_watchlist")]])
        await query.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
    elif data == "profile_stats":
        stats_text = format_user_stats(user_id)
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Retour", callback_data="profile_main")]])
        await query.message.edit_text(stats_text, parse_mode="HTML", reply_markup=keyboard)
    elif data == "profile_achievements":
        achievements = db.get_achievements(user_id)
        if not achievements:
            await query.message.edit_text(
                "🏆 <b>Vos Achievements</b>\nVous n'avez pas encore débloqué d'achievements.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Retour", callback_data="profile_main")]])
            )
            return
        text = "🏆 <b>Vos Achievements</b>\n"
        for i, achievement in enumerate(achievements, 1):
            text += f"{i}. {achievement['name']}\n"
            text += f"   <i>Débloqué le {achievement['achieved_at'][:10]}</i>\n"
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Retour", callback_data="profile_main")]])
        await query.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
    elif data == "profile_recommendations":
        await query.message.edit_text(
            "🎯 <b>Chargement de vos recommandations personnalisées...</b>",
            parse_mode="HTML"
        )
        recommendations = get_personal_recommendations(user_id, 5)
        if not recommendations:
            await query.message.edit_text(
                "🎯 <b>Recommandations Personnalisées</b>\nImpossible de générer des recommandations pour le moment.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Retour", callback_data="profile_main")]])
            )
            return
        text = "🎯 <b>Recommandations Personnalisées</b>\n"
        text += "Basé sur vos préférences, nous vous recommandons:\n"
        for i, anime in enumerate(recommendations, 1):
            title = escape_html(decode_html_entities(anime.get("title", "Titre inconnu")))
            score = escape_html(str(anime.get("score", "N/A")))
            text += f"{i}. {title} ⭐ {score}\n"
        # Créer un clavier avec les recommandations
        keyboard = []
        for anime in recommendations:
            title = decode_html_entities(anime.get("title", "Sans titre"))
            if len(title) > 30:
                title = title[:27] + "..."
            keyboard.append([InlineKeyboardButton(title, callback_data=f"anime_{anime['mal_id']}")])
        keyboard.append([InlineKeyboardButton("🔙 Retour", callback_data="profile_main")])
        await query.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    elif data == "profile_back":
        keyboard = create_profile_keyboard()
        await query.message.edit_text(
            "👤 <b>Votre Profil Anime</b>\nSélectionnez une option:",
            parse_mode="HTML",
            reply_markup=keyboard
        )
    # No operation - ne rien faire
    elif data == "noop":
        pass

# ──────────────────────────
# Messages & erreurs
# ──────────────────────────
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    db.add_user(user.id, user.username, user.first_name, user.last_name, user.language_code)
    if update.message.chat.type in ["group", "supergroup"]:
        if context.bot.username and f"@{context.bot.username}" in update.message.text:
            # Extraire le query après la mention du bot
            query = update.message.text.replace(f"@{context.bot.username}", "").strip()
            if query:
                await perform_search(update, query, context)
            else:
                await update.message.reply_text("❌ Veuillez spécifier un anime après la mention.", parse_mode="HTML")
        return
    query = (update.message.text or "").strip()
    if query:
        await perform_search(update, query, context)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Erreur lors du traitement de la mise à jour {update}: {context.error}")
    try:
        if update and getattr(update, "message", None):
            await update.message.reply_text("❌ Une erreur s'est produite. Veuillez réessayer plus tard.", parse_mode="HTML")
    except Exception:
        pass

# ──────────────────────────
# Lancement
# ──────────────────────────
def main():
    if not TOKEN:
        raise RuntimeError("La variable d'environnement TOKEN est manquante.")
    app = Application.builder().token(TOKEN).build()
    # Commandes
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("aide", help_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("recherche", search_command))
    app.add_handler(CommandHandler("anime", anime_command))
    app.add_handler(CommandHandler("saison", season_command))
    app.add_handler(CommandHandler("personnage", character_command))
    app.add_handler(CommandHandler("character", character_command))  # alias
    app.add_handler(CommandHandler("top", top_command))
    app.add_handler(CommandHandler("random", random_command))
    app.add_handler(CommandHandler("planning", planning_command))
    app.add_handler(CommandHandler("profil", profile_command))
    # Inline & messages
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    # Erreurs
    app.add_error_handler(error_handler)
    print("✅ Bot anime lancé…")
    app.run_polling()

if __name__ == "__main__":
    main()
