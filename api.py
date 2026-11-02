import json
import os
import httpx
from fastapi import FastAPI, HTTPException, Depends, Query, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from aiocache import Cache
from aiocache.serializers import JsonSerializer
import aiosqlite
from database import DB, init_db
from auth import current_user

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_IDS = {123456789}

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
cache = Cache(Cache.MEMORY, serializer=JsonSerializer())

async def ensure_user(user):
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users(id, username, first_name) VALUES (?,?,?)",
            (user.get("id"), user.get("username"), user.get("first_name"))
        )
        await db.commit()

class PostIn(BaseModel):
    title: str
    body: str
    tag: str = "general"
    image_file_id: str | None = None
class CommentIn(BaseModel):
    post_id: int
    parent_id: int | None = None
    body: str
class VoteIn(BaseModel):
    target_type: str
    target_id: int
    value: int

@app.get("/api/posts")
async def list_posts(sort: str = "new", tag: str | None = None, q: str | None = None, page: int = 1, limit: int = 20, user=Depends(current_user)):
    try:
        await ensure_user(user)
        if limit > 50: limit = 50
        offset = (page - 1) * limit
        order = {"new": "p.created_at DESC", "top": "p.score DESC, p.created_at DESC", "hot": "(p.score * 1.0 / (julianday('now') - julianday(p.created_at) + 2)) DESC"}.get(sort, "p.created_at DESC")

        async with aiosqlite.connect(DB) as db:
            db.row_factory = aiosqlite.Row
            if q:
                cursor = await db.execute(
                    """SELECT p.id, p.title, p.tag, p.score, p.views, p.created_at, u.username, u.first_name, (SELECT COUNT(*) FROM comments c WHERE c.post_id=p.id) AS comments
                       FROM posts_fts f JOIN posts p ON p.id = f.rowid JOIN users u ON u.id = p.author_id
                       WHERE posts_fts MATCH ? AND p.is_hidden = 0 ORDER BY p.score DESC LIMIT ? OFFSET ?""", (q + "*", limit, offset))
            else:
                where = ["p.is_hidden = 0"]
                params = []
                if tag:
                    where.append("p.tag = ?"); params.append(tag)
                params += [limit, offset]
                cursor = await db.execute(
                    f"""SELECT p.id, p.title, p.tag, p.score, p.views, p.created_at, u.username, u.first_name, (SELECT COUNT(*) FROM comments c WHERE c.post_id=p.id) AS comments
                        FROM posts p JOIN users u ON u.id=p.author_id WHERE {' AND '.join(where)} ORDER BY {order} LIMIT ? OFFSET ?""", params)
            rows = [dict(r) for r in await cursor.fetchall()]
        return {"posts": rows, "page": page, "has_more": len(rows) == limit}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/posts/{post_id}")
async def get_post(post_id: int, user=Depends(current_user)):
    await ensure_user(user)
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("UPDATE posts SET views = views + 1 WHERE id=?", (post_id,))
        await db.commit()
        cur = await db.execute("SELECT p.*, u.username, u.first_name, u.karma as author_karma FROM posts p JOIN users u ON u.id=p.author_id WHERE p.id=? AND p.is_hidden=0", (post_id,))
        post = await cur.fetchone()
        if not post: raise HTTPException(404)
        cur = await db.execute("SELECT c.*, u.username, u.first_name, u.karma as author_karma FROM comments c JOIN users u ON u.id=c.author_id WHERE c.post_id=? AND c.is_hidden=0 ORDER BY c.created_at", (post_id,))
        comments = [dict(r) for r in await cur.fetchall()]
        cur = await db.execute("SELECT value FROM votes WHERE user_id=? AND target_type='post' AND target_id=?", (user.get("id"), post_id))
        my_vote = await cur.fetchone()
        post = dict(post); post["my_vote"] = my_vote[0] if my_vote else 0
        cur = await db.execute("SELECT 1 FROM subscriptions WHERE user_id=? AND post_id=?", (user.get("id"), post_id))
        post["subscribed"] = bool(await cur.fetchone())
    return {"post": post, "comments": comments}

@app.post("/api/posts")
async def create_post(data: PostIn, user=Depends(current_user)):
    await ensure_user(user)
    if not data.title.strip() or len(data.title) > 200: raise HTTPException(400, "bad title")
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("INSERT INTO posts(author_id,title,body,tag,image_file_id) VALUES (?,?,?,?,?)", (user.get("id"), data.title, data.body, data.tag, data.image_file_id))
        await db.execute("UPDATE users SET karma = karma + 2 WHERE id = ?", (user.get("id"),))
        await db.commit()
        return {"id": cur.lastrowid}

@app.post("/api/comments")
async def create_comment(data: CommentIn, user=Depends(current_user)):
    await ensure_user(user)
    if not data.body.strip(): raise HTTPException(400, "empty")
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("INSERT INTO comments(post_id,parent_id,author_id,body) VALUES (?,?,?,?)", (data.post_id, data.parent_id, user.get("id"), data.body))
        await db.execute("UPDATE users SET karma = karma + 1 WHERE id = ?", (user.get("id"),))
        await db.commit()
        return {"id": cur.lastrowid}

@app.post("/api/vote")
async def vote(data: VoteIn, user=Depends(current_user)):
    await ensure_user(user)
    if data.target_type not in ("post", "comment") or data.value not in (1, -1, 0): raise HTTPException(400)
    table = "posts" if data.target_type == "post" else "comments"
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(f"SELECT author_id FROM {table} WHERE id=?", (data.target_id,))
        target = await cur.fetchone()
        if not target: raise HTTPException(404)
        cur = await db.execute("SELECT value FROM votes WHERE user_id=? AND target_type=? AND target_id=?", (user.get("id"), data.target_type, data.target_id))
        old = await cur.fetchone()
        old_v = old[0] if old else 0
        delta = data.value - old_v
        if delta == 0: return {"ok": True}
        if data.value == 0:
            await db.execute("DELETE FROM votes WHERE user_id=? AND target_type=? AND target_id=?", (user.get("id"), data.target_type, data.target_id))
        else:
            await db.execute("INSERT INTO votes(user_id,target_type,target_id,value) VALUES (?,?,?,?) ON CONFLICT(user_id,target_type,target_id) DO UPDATE SET value=excluded.value", (user.get("id"), data.target_type, data.target_id, data.value))
        await db.execute(f"UPDATE {table} SET score=score+? WHERE id=?", (delta, data.target_id))
        await db.commit()
    return {"ok": True}

@app.get("/api/notifications")
async def notifications(user=Depends(current_user)):
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC LIMIT 50", (user.get("id"),))
        rows = [dict(r) for r in await cur.fetchall()]
        for r in rows: r["payload"] = json.loads(r["payload"])
        return rows

@app.get("/api/users/{user_id}")
async def user_profile(user_id: int, user=Depends(current_user)):
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT id,username,first_name,karma,created_at FROM users WHERE id=?", (user_id,))
        u = await cur.fetchone()
        if not u: raise HTTPException(404)
        cur = await db.execute("SELECT COUNT(*) as c FROM posts WHERE author_id=? AND is_hidden=0", (user_id,))
        return {**dict(u), "posts_count": (await cur.fetchone())["c"]}

@app.on_event("startup")
async def _startup():
    try:
        await init_db()
        print("✅ БД успешно создана/проверена!")
    except Exception as e:
        print("❌ ОШИБКА ИНИЦИАЛИЗАЦИИ БД:", str(e))

@app.get("/healthz")
async def healthz():
    return {"status": "ok"}

app.mount("/", StaticFiles(directory="static", html=True), name="static")
