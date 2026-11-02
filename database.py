import aiosqlite

DB = "forum.db"

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, karma INTEGER DEFAULT 0, is_banned INTEGER DEFAULT 0, ban_reason TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS posts (id INTEGER PRIMARY KEY AUTOINCREMENT, author_id INTEGER NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL, tag TEXT DEFAULT 'general', image_file_id TEXT, score INTEGER DEFAULT 0, views INTEGER DEFAULT 0, is_hidden INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(author_id) REFERENCES users(id));
CREATE TABLE IF NOT EXISTS comments (id INTEGER PRIMARY KEY AUTOINCREMENT, post_id INTEGER NOT NULL, parent_id INTEGER, author_id INTEGER NOT NULL, body TEXT NOT NULL, score INTEGER DEFAULT 0, is_hidden INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(post_id) REFERENCES posts(id));
CREATE TABLE IF NOT EXISTS votes (user_id INTEGER NOT NULL, target_type TEXT NOT NULL, target_id INTEGER NOT NULL, value INTEGER NOT NULL, PRIMARY KEY(user_id, target_type, target_id));
CREATE TABLE IF NOT EXISTS reports (id INTEGER PRIMARY KEY AUTOINCREMENT, reporter_id INTEGER NOT NULL, target_type TEXT NOT NULL, target_id INTEGER NOT NULL, reason TEXT, resolved INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS notifications (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, type TEXT NOT NULL, payload TEXT NOT NULL, is_read INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS subscriptions (user_id INTEGER NOT NULL, post_id INTEGER NOT NULL, PRIMARY KEY(user_id, post_id));
CREATE TABLE IF NOT EXISTS tags (name TEXT PRIMARY KEY, posts_count INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS idx_posts_created ON posts(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_posts_score ON posts(score DESC);
CREATE VIRTUAL TABLE IF NOT EXISTS posts_fts USING fts5(title, body, content='posts', content_rowid='id');
CREATE TRIGGER IF NOT EXISTS posts_ai AFTER INSERT ON posts BEGIN INSERT INTO posts_fts(rowid, title, body) VALUES (new.id, new.title, new.body); END;
CREATE TRIGGER IF NOT EXISTS posts_ad AFTER DELETE ON posts BEGIN INSERT INTO posts_fts(posts_fts, rowid, title, body) VALUES('delete', old.id, old.title, old.body); END;
CREATE TRIGGER IF NOT EXISTS posts_au AFTER UPDATE ON posts BEGIN INSERT INTO posts_fts(posts_fts, rowid, title, body) VALUES('delete', old.id, old.title, old.body); INSERT INTO posts_fts(rowid, title, body) VALUES (new.id, new.title, new.body); END;
"""

async def init_db():
    async with aiosqlite.connect(DB) as db:
        await db.executescript(SCHEMA)
        await db.commit()
        print("✅ База данных успешно инициализирована!")
