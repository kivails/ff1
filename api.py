import json, os, httpx, datetime
from fastapi import FastAPI, HTTPException, Depends, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import aiosqlite
from database import DB, init_db
from auth import current_user

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_IDS = {5024935475}
TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

async def ensure_user(user):
    async with aiosqlite.connect(DB) as db:
        await db.execute("INSERT OR IGNORE INTO users(id, username, first_name) VALUES (?,?,?)",
                         (user.get("id"), user.get("username"), user.get("first_name")))
        await db.commit()

async def check_achievements(user_id):
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("SELECT COUNT(*) FROM posts WHERE author_id=?", (user_id,))
        if (await cur.fetchone())[0] >= 1:
            await db.execute("INSERT OR IGNORE INTO achievements VALUES (?, 'first_post')", (user_id,))
        cur = await db.execute("SELECT SUM(score) FROM posts WHERE author_id=?", (user_id,))
        p_karma = (await cur.fetchone())[0] or 0
        if p_karma >= 100:
            await db.execute("INSERT OR IGNORE INTO achievements VALUES (?, 'karma_100')", (user_id,))
        await db.commit()

class PostIn(BaseModel):
    title: str; body: str; tags: str = "general"; image_file_id: str | None = None
class CommentIn(BaseModel):
    post_id: int; parent_id: int | None = None; body: str
class VoteIn(BaseModel):
    target_type: str; target_id: int; value: int
class ProfileUpdate(BaseModel):
    custom_nick: str | None = None; bio: str | None = None; theme: str | None = None
class ReactionIn(BaseModel):
    target_type: str; target_id: int; emoji: str
class GiftIn(BaseModel):
    to_id: int; gift: str

@app.get("/ping")
async def ping():
    return {"status": "alive"}

@app.get("/api/posts")
async def list_posts(sort: str = "new", q: str | None = None, user=Depends(current_user)):
    await ensure_user(user)
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        query = """SELECT p.*, u.username, u.first_name, u.custom_nick, u.badge,
                   (SELECT COUNT(*) FROM comments c WHERE c.post_id=p.id) AS comments
                   FROM posts p JOIN users u ON u.id=p.author_id 
                   WHERE p.status='approved' AND p.is_hidden=0"""
        params = []
        if q: query += " AND p.tags LIKE ?"; params.append(f"%{q}%")
        query += " AND p.created_at >= date('now', '-1 day')" if sort == "day_top" else ""
        query += " ORDER BY p.score DESC" if sort == "day_top" else " ORDER BY p.created_at DESC"
        query += " LIMIT 50"
        cur = await db.execute(query, params)
        posts = [dict(r) for r in await cur.fetchall()]
        for p in posts:
            cur = await db.execute("SELECT emoji, COUNT(*) as c FROM reactions WHERE target_type='post' AND target_id=? GROUP BY emoji", (p["id"],))
            p["reactions"] = {r["emoji"]: r["c"] for r in await cur.fetchall()}
    return {"posts": posts}

@app.post("/api/posts")
async def create_post(data: PostIn, user=Depends(current_user)):
    await ensure_user(user)
    async with aiosqlite.connect(DB) as db:
        tags_list = [t.strip().replace('#', '') for t in data.tags.split(',') if t.strip()]
        tags_str = ', '.join(tags_list[:3])
        status = 'approved' if user.get("id") in ADMIN_IDS else 'pending'
        cur = await db.execute("INSERT INTO posts(author_id,title,body,tags,image_file_id,status) VALUES (?,?,?,?,?,?)",
                               (user.get("id"), data.title, data.body, tags_str, data.image_file_id, status))
        post_id = cur.lastrowid
        await db.execute("UPDATE users SET crystals = crystals + 10 WHERE id=?", (user.get("id"),))
        await db.commit()
    await check_achievements(user.get("id"))
    if status == 'pending':
        for admin in ADMIN_IDS:
            kb = {"inline_keyboard": [[{"text": "✅ Одобрить", "callback_data": f"mod_ok_{post_id}"},{"text": "❌ Отклонить", "callback_data": f"mod_no_{post_id}"}]]}
            caption = f"🛡️ <b>Пост на модерацию!</b>\nОт: {user.get('first_name')}\n\n<b>{data.title}</b>\n{data.body[:200]}...\n\nТеги: {tags_str}"
            async with httpx.AsyncClient() as client:
                if data.image_file_id:
                    await client.post(f"{TG_API}/sendPhoto", data={"chat_id": admin, "photo": data.image_file_id, "caption": caption, "parse_mode": "HTML", "reply_markup": json.dumps(kb)})
                else:
                    await client.post(f"{TG_API}/sendMessage", data={"chat_id": admin, "text": caption, "parse_mode": "HTML", "reply_markup": json.dumps(kb)})
    return {"id": post_id, "status": status}

@app.get("/api/posts/{post_id}")
async def get_post(post_id: int, user=Depends(current_user)):
    await ensure_user(user)
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT 1 FROM post_views WHERE user_id=? AND post_id=?", (user.get("id"), post_id))
        if not await cur.fetchone():
            await db.execute("UPDATE posts SET views = views + 1 WHERE id=?", (post_id,))
            await db.execute("INSERT INTO post_views VALUES (?,?)", (user.get("id"), post_id))
            await db.commit()
        cur = await db.execute("SELECT p.*, u.username, u.first_name, u.custom_nick, u.badge FROM posts p JOIN users u ON u.id=p.author_id WHERE p.id=? AND p.status='approved'", (post_id,))
        post = await cur.fetchone()
        if not post: raise HTTPException(404)
        cur = await db.execute("SELECT c.*, u.username, u.first_name, u.custom_nick, u.badge FROM comments c JOIN users u ON u.id=c.author_id WHERE c.post_id=? AND c.is_hidden=0 ORDER BY c.created_at", (post_id,))
        comments = [dict(r) for r in await cur.fetchall()]
        cur = await db.execute("SELECT emoji FROM reactions WHERE user_id=? AND target_type='post' AND target_id=?", (user.get("id"), post_id))
        post = dict(post); post["my_reactions"] = [r["emoji"] for r in await cur.fetchall()]
    return {"post": post, "comments": comments}

@app.post("/api/comments")
async def create_comment(data: CommentIn, user=Depends(current_user)):
    await ensure_user(user)
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("INSERT INTO comments(post_id,parent_id,author_id,body) VALUES (?,?,?,?)", (data.post_id, data.parent_id, user.get("id"), data.body))
        await db.commit()
    return {"id": cur.lastrowid}

@app.post("/api/vote")
async def vote(data: VoteIn, user=Depends(current_user)):
    await ensure_user(user)
    async with aiosqlite.connect(DB) as db:
        table = "posts" if data.target_type == "post" else "comments"
        cur = await db.execute("SELECT value FROM votes WHERE user_id=? AND target_type=? AND target_id=?", (user.get("id"), data.target_type, data.target_id))
        old = await cur.fetchone()
        delta = data.value - (old[0] if old else 0)
        if data.value == 0:
            await db.execute("DELETE FROM votes WHERE user_id=? AND target_type=? AND target_id=?", (user.get("id"), data.target_type, data.target_id))
        else:
            await db.execute("INSERT INTO votes VALUES (?,?,?,?) ON CONFLICT DO UPDATE SET value=excluded.value", (user.get("id"), data.target_type, data.target_id, data.value))
        await db.execute(f"UPDATE {table} SET score=score+? WHERE id=?", (delta, data.target_id))
        await db.commit()
    return {"ok": True}

@app.post("/api/react")
async def react(data: ReactionIn, user=Depends(current_user)):
    await ensure_user(user)
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("SELECT emoji FROM reactions WHERE user_id=? AND target_type=? AND target_id=?", (user.get("id"), data.target_type, data.target_id))
        my_reactions = [r[0] for r in await cur.fetchall()]
        max_reactions = 3 if user.get("id") in ADMIN_IDS else 1
        if data.emoji in my_reactions:
            await db.execute("DELETE FROM reactions WHERE user_id=? AND target_type=? AND target_id=? AND emoji=?", (user.get("id"), data.target_type, data.target_id, data.emoji))
        else:
            if len(my_reactions) >= max_reactions: raise HTTPException(400, "Лимит реакций!")
            await db.execute("INSERT INTO reactions VALUES (?,?,?,?)", (user.get("id"), data.target_type, data.target_id, data.emoji))
        await db.commit()
    return {"ok": True}

@app.post("/api/buy_gift")
async def buy_gift(data: GiftIn, user=Depends(current_user)):
    costs = {"heart": 10, "star": 30, "crown": 100}
    if data.gift not in costs: raise HTTPException(400)
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("SELECT crystals FROM users WHERE id=?", (user.get("id"),))
        if (await cur.fetchone())[0] < costs[data.gift]: raise HTTPException(400, "Мало кристаллов!")
        await db.execute("UPDATE users SET crystals = crystals - ? WHERE id=?", (costs[data.gift], user.get("id")))
        await db.execute("INSERT INTO gifts(from_id, to_id, gift_name) VALUES (?, ?, ?)", (user.get("id"), data.to_id, data.gift))
        await db.commit()
    return {"ok": True}

@app.get("/api/profile/{user_id}")
async def get_profile(user_id: int, user=Depends(current_user)):
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM users WHERE id=?", (user_id,))
        u = await cur.fetchone()
        if not u: raise HTTPException(404)
        cur = await db.execute("SELECT SUM(score) FROM posts WHERE author_id=?", (user_id,))
        p_karma = (await cur.fetchone())[0] or 0
        cur = await db.execute("SELECT SUM(score) FROM comments WHERE author_id=?", (user_id,))
        c_karma = (await cur.fetchone())[0] or 0
        cur = await db.execute("SELECT title FROM posts WHERE author_id=? ORDER BY score DESC LIMIT 1", (user_id,))
        top_post = await cur.fetchone()
        cur = await db.execute("SELECT gift_name, COUNT(*) as c FROM gifts WHERE to_id=? GROUP BY gift_name", (user_id,))
        gifts = [{"name": r["gift_name"], "count": r["c"]} for r in await cur.fetchall()]
        cur = await db.execute("SELECT ach_name FROM achievements WHERE user_id=?", (user_id,))
        achs = [r["ach_name"] for r in await cur.fetchall()]
    return {**dict(u), "karma": p_karma + c_karma, "level": (p_karma + c_karma) // 10, "top_post": dict(top_post) if top_post else None, "gifts": gifts, "achievements": achs}

@app.post("/api/profile")
async def update_profile(data: ProfileUpdate, user=Depends(current_user)):
    async with aiosqlite.connect(DB) as db:
        if data.custom_nick: await db.execute("UPDATE users SET custom_nick=? WHERE id=?", (data.custom_nick, user.get("id")))
        if data.bio is not None: await db.execute("UPDATE users SET bio=? WHERE id=?", (data.bio, user.get("id")))
        if data.theme: await db.execute("UPDATE users SET theme=? WHERE id=?", (data.theme, user.get("id")))
        await db.commit()
    return {"ok": True}

@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...), user=Depends(current_user)):
    content = await file.read()
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{TG_API}/sendDocument", data={"chat_id": user.get("id")}, files={"document": ("file.gif", content)})
        res = r.json()
        if not res.get("ok"): raise HTTPException(500, "Ошибка загрузки")
        file_id = res["result"]["document"]["file_id"]
        await client.post(f"{TG_API}/deleteMessage", json={"chat_id": user.get("id"), "message_id": res["result"]["message_id"]})
    return {"file_id": file_id}

@app.get("/api/image/{post_id}")
async def get_image(post_id: int):
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("SELECT image_file_id FROM posts WHERE id=?", (post_id,))
        row = await cur.fetchone()
    if not row or not row[0]: raise HTTPException(404)
    async with httpx.AsyncClient() as c:
        r = await c.get(f"{TG_API}/getFile?file_id={row[0]}")
        path = r.json()["result"]["file_path"]
        img = await c.get(f"https://api.telegram.org/file/bot{BOT_TOKEN}/{path}")
    return StreamingResponse(iter([img.content]), media_type="image/jpeg")

@app.get("/api/settings")
async def get_settings():
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT key, value FROM settings")
        return {r["key"]: r["value"] for r in await cur.fetchall()}

@app.on_event("startup")
async def _startup(): await init_db()

app.mount("/", StaticFiles(directory="static", html=True), name="static")
