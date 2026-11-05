import aiosqlite

DB = "rareads.db"

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, 
    bio TEXT DEFAULT '', custom_nick TEXT, theme TEXT DEFAULT 'default',
    crystals INTEGER DEFAULT 0, frame TEXT DEFAULT 'none', 
    owned_frames TEXT DEFAULT '',
    badge TEXT DEFAULT '', banner TEXT DEFAULT 'none',
    avatar TEXT DEFAULT '',
    is_banned INTEGER DEFAULT 0, is_frozen INTEGER DEFAULT 0,
    last_daily TIMESTAMP, last_roulette TIMESTAMP,
    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    referred_by INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT, author_id INTEGER NOT NULL, 
    title TEXT NOT NULL, body TEXT NOT NULL, tags TEXT DEFAULT 'general', 
    image_file_id TEXT, score INTEGER DEFAULT 0, views INTEGER DEFAULT 0, 
    is_hidden INTEGER DEFAULT 0, status TEXT DEFAULT 'approved', 
    is_anonymous INTEGER DEFAULT 0,
    is_adult INTEGER DEFAULT 0,
    style TEXT DEFAULT 'default',
    mentioned_user INTEGER DEFAULT NULL,
    boost_until TIMESTAMP DEFAULT NULL,
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
CREATE TABLE IF NOT EXISTS custom_reactions (
    name TEXT PRIMARY KEY, file_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS gifts (
    id INTEGER PRIMARY KEY AUTOINCREMENT, from_id INTEGER NOT NULL, 
    to_id INTEGER NOT NULL, gift_name TEXT NOT NULL, description TEXT DEFAULT '', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS achievements (
    user_id INTEGER NOT NULL, ach_name TEXT NOT NULL, 
    PRIMARY KEY(user_id, ach_name)
);
CREATE TABLE IF NOT EXISTS subscriptions (
    user_id INTEGER NOT NULL, target_id INTEGER NOT NULL, 
    PRIMARY KEY(user_id, target_id)
);
CREATE TABLE IF NOT EXISTS banners (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, price INTEGER NOT NULL, image_url TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS games_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, game TEXT NOT NULL, win INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS strikes (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, reason TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT, reporter_id INTEGER NOT NULL, target_type TEXT NOT NULL, target_id INTEGER NOT NULL, reason TEXT NOT NULL, resolved INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS promo_uses (
    user_id INTEGER NOT NULL, code TEXT NOT NULL, 
    PRIMARY KEY(user_id, code)
);
CREATE TABLE IF NOT EXISTS saved_posts (
    user_id INTEGER NOT NULL, post_id INTEGER NOT NULL, 
    PRIMARY KEY(user_id, post_id)
);
CREATE TABLE IF NOT EXISTS reposts (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, post_id INTEGER NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS boosts (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, post_id INTEGER NOT NULL, boost_type TEXT NOT NULL, expires_at TIMESTAMP NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS polls (
    id INTEGER PRIMARY KEY AUTOINCREMENT, post_id INTEGER NOT NULL, question TEXT NOT NULL, options TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS poll_votes (
    user_id INTEGER NOT NULL, poll_id INTEGER NOT NULL, option_index INTEGER NOT NULL, 
    PRIMARY KEY(user_id, poll_id)
);
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, type TEXT NOT NULL, payload TEXT NOT NULL, is_read INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS tags (name TEXT PRIMARY KEY, color TEXT DEFAULT '#ffb7c5', posts_count INTEGER DEFAULT 0);
"""

async def add_column_if_missing(db, table, column, col_type, default=None):
    try:
        if default is not None:
            await db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type} DEFAULT {default}")
        else:
            await db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
    except aiosqlite.OperationalError:
        pass

async def init_db():
    async with aiosqlite.connect(DB) as db:
        await db.executescript(SCHEMA)
        
        # Миграции для старых баз (добавляют недостающие колонки, не удаляя данные)
        await add_column_if_missing(db, "users", "avatar", "TEXT", "''")
        await add_column_if_missing(db, "users", "banner", "TEXT", "'none'")
        await add_column_if_missing(db, "users", "last_roulette", "TIMESTAMP", "NULL")
        await add_column_if_missing(db, "users", "last_seen", "TIMESTAMP", "CURRENT_TIMESTAMP")
        await add_column_if_missing(db, "users", "is_frozen", "INTEGER", "0")
        await add_column_if_missing(db, "users", "owned_frames", "TEXT", "''")
        await add_column_if_missing(db, "posts", "is_anonymous", "INTEGER", "0")
        await add_column_if_missing(db, "posts", "is_adult", "INTEGER", "0")
        await add_column_if_missing(db, "posts", "style", "TEXT", "'default'")
        await add_column_if_missing(db, "posts", "mentioned_user", "INTEGER", "NULL")
        await add_column_if_missing(db, "posts", "boost_until", "TIMESTAMP", "NULL")
        await add_column_if_missing(db, "users", "profile_pattern", "TEXT", "'none'")
        await add_column_if_missing(db, "gifts", "description", "TEXT", "''")
        
        await db.execute("INSERT OR IGNORE INTO tags(name) VALUES ('general'), ('anime'), ('news')")
        await db.execute("INSERT OR IGNORE INTO settings(key, value) VALUES ('playlist', '[]'), ('support_link', 'https://t.me/kvails')")
        
        # Базовые баннеры (5 аниме-вариантов)
        await db.execute("INSERT OR IGNORE INTO banners(name, price, image_url) VALUES ('Anime 1', 100, 'https://images.unsplash.com/photo-1578632767115-351597cf2477?q=80&w=1000&auto=format&fit=crop')")
        await db.execute("INSERT OR IGNORE INTO banners(name, price, image_url) VALUES ('Anime 2', 150, 'https://images.unsplash.com/photo-1522383225653-ed111181a951?q=80&w=1000')")
        await db.execute("INSERT OR IGNORE INTO banners(name, price, image_url) VALUES ('Anime 3', 200, 'https://images.unsplash.com/photo-1495616811223-4d98c6e9c869?q=80&w=1000')")
        await db.execute("INSERT OR IGNORE INTO banners(name, price, image_url) VALUES ('Anime 4', 250, 'https://images.unsplash.com/photo-1555680202-c86f0e12f086?q=80&w=1000')")
        await db.execute("INSERT OR IGNORE INTO banners(name, price, image_url) VALUES ('Anime 5', 300, 'https://images.unsplash.com/photo-1462331940025-496dfbfc7564?q=80&w=1000')")
        await db.commit()
