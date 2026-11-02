import aiosqlite

DB = "/data/rareads.db"

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, 
    bio TEXT DEFAULT '', custom_nick TEXT, theme TEXT DEFAULT 'default',
    crystals INTEGER DEFAULT 0, frame TEXT DEFAULT 'none', badge TEXT DEFAULT '',
    is_banned INTEGER DEFAULT 0, last_daily TIMESTAMP,
    referred_by INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT, author_id INTEGER NOT NULL, 
    title TEXT NOT NULL, body TEXT NOT NULL, tags TEXT DEFAULT 'general', 
    image_file_id TEXT, score INTEGER DEFAULT 0, views INTEGER DEFAULT 0, 
    is_hidden INTEGER DEFAULT 0, status TEXT DEFAULT 'approved', 
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT, post_id INTEGER NOT NULL, 
    parent_id INTEGER, author_id INTEGER NOT NULL, body TEXT NOT NULL, 
    score INTEGER DEFAULT 0, is_hidden INTEGER DEFAULT 0, 
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS post_views (
    user_id INTEGER NOT NULL, post_id INTEGER NOT NULL, 
    PRIMARY KEY(user_id, post_id)
);
CREATE TABLE IF NOT EXISTS votes (
    user_id INTEGER NOT NULL, target_type TEXT NOT NULL, 
    target_id INTEGER NOT NULL, value INTEGER NOT NULL, 
    PRIMARY KEY(user_id, target_type, target_id)
);
CREATE TABLE IF NOT EXISTS reactions (
    user_id INTEGER NOT NULL, target_type TEXT NOT NULL, target_id INTEGER NOT NULL, 
    emoji TEXT NOT NULL, PRIMARY KEY(user_id, target_type, target_id, emoji)
);
CREATE TABLE IF NOT EXISTS gifts (
    id INTEGER PRIMARY KEY AUTOINCREMENT, from_id INTEGER NOT NULL, 
    to_id INTEGER NOT NULL, gift_name TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS achievements (
    user_id INTEGER NOT NULL, ach_name TEXT NOT NULL, 
    PRIMARY KEY(user_id, ach_name)
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS tags (name TEXT PRIMARY KEY, color TEXT DEFAULT '#ffb7c5', posts_count INTEGER DEFAULT 0);
"""

async def init_db():
    import os
    if not os.path.exists("/data"):
        os.makedirs("/data")
    async with aiosqlite.connect(DB) as db:
        await db.executescript(SCHEMA)
        await db.execute("INSERT OR IGNORE INTO tags(name) VALUES ('general'), ('anime'), ('news')")
        await db.execute("INSERT OR IGNORE INTO settings(key, value) VALUES ('bg_music_1', 'https://cdn.pixabay.com/download/audio/2022/03/15/audio_c8c8a73467.mp3'), ('bg_music_2', 'https://cdn.pixabay.com/download/audio/2022/01/18/audio_d0c6ff1bab.mp3')")
        await db.commit()
