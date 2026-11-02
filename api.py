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
ADMIN_IDS = {5024935475}# ТВОЙ ID (узнай в @userinfobot)
TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

async def ensure_user(user):
    async with aiosqlite.connect(DB) as db:
        await db.execute("INSERT OR IGNORE INTO users(id, username, first_name) VALUES (?,?,?)",
                         (user.get("id"), user.get("username"), user.get("first_name")))
        await db.commit()

async def send_tg(chat_id, text, reply_markup=None):
    async with httpx.AsyncClient() as client:
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
        if reply_markup: payload["reply_markup"] = json.dumps(reply_markup)
        await client.post(f"{TG_API}/sendMessage", json=payload)

# ============ Модели ============
class PostIn(BaseModel):
    title: str; body: str; tag: str = "general"; image_file_id: str | None = None
class CommentIn(BaseModel):
    post_id: int; parent_id: int | None = None; body: str
class VoteIn(BaseModel):
    target_type: str; target_id: int; value: int
class ProfileUpdate(BaseModel):
    custom_nick: str | None = None; bio: str | None = None; theme: str | None = None

# ============ API ============
@app.get("/api/posts")
async def list_posts(tag: str | None = None, user=Depends(current_user)):
    await ensure_user(user)
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        query = """SELECT p.*, u.username, u.first_name, u.custom_nick,
                   (SELECT COUNT(*) FROM comments c WHERE c.post_id=p.id) AS comments
                   FROM posts p JOIN users u ON u.id=p.author_id 
                   WHERE p.status='approved' AND p.is_hidden=0"""
        params = []
        if tag:
            query += " AND p.tag = ?"; params.append(tag)
        query += " ORDER BY p.created_at DESC LIMIT 50"
        cur = await db.execute(query, params)
        posts = [dict(r) for r in await cur.fetchall()]
        
        # Получаем цвета тегов
        cur = await db.execute("SELECT name, color FROM tags")
        tag_colors = {r["name"]: r["color"] for r in await cur.fetchall()}
        for p in posts: p["tag_color"] = tag_colors.get(p["tag"], "#ff007f")
    return {"posts": posts}

@app.get("/api/tags")
async def get_tags():
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM tags ORDER BY posts_count DESC LIMIT 15")
        return [dict(r) for r in await cur.fetchall()]

@app.post("/api/posts")
async def create_post(data: PostIn, user=Depends(current_user)):
    await ensure_user(user)
    async with aiosqlite.connect(DB) as db:
        # Проверка КД 15 минут
        cur = await db.execute("SELECT created_at FROM posts WHERE author_id=? ORDER BY id DESC LIMIT 1", (user.get("id"),))
        last = await cur.fetchone()
        if last:
            last_time = datetime.datetime.fromisoformat(last[0])
            if (datetime.datetime.utcnow() - last_time).total_seconds() < 900:
                raise HTTPException(400, "Кулдаун 15 минут между постами!")

        status = 'approved' if user.get("id") in ADMIN_IDS else 'pending'
        cur = await db.execute("INSERT INTO posts(author_id,title,body,tag,image_file_id,status) VALUES (?,?,?,?,?,?)",
                               (user.get("id"), data.title, data.body, data.tag, data.image_file_id, status))
        post_id = cur.lastrowid
        await db.execute("UPDATE tags SET posts_count = posts_count + 1 WHERE name=?", (data.tag,))
        await db.commit()

    if status == 'pending':
        # Отправляем админам на модерацию
        for admin in ADMIN_IDS:
            kb = {"inline_keyboard": [[
                {"text": "✅ Одобрить", "callback_data": f"mod_ok_{post_id}"},
                {"text": "❌ Отклонить", "callback_data": f"mod_no_{post_id}"}
            ]]}
            await send_tg(admin, f"🛡️ <b>Новый пост на модерацию!</b>\nОт: {user.get('first_name')}\n\n<b>{data.title}</b>\n{data.body[:200]}...", reply_markup=kb)
    return {"id": post_id, "status": status}

@app.get("/api/posts/{post_id}")
async def get_post(post_id: int, user=Depends(current_user)):
    await ensure_user(user)
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        # Умные просмотры: +1 только если юзер не смотрел (упрощенно)
        await db.execute("UPDATE posts SET views = views + 1 WHERE id=?", (post_id,))
        await db.commit()
        
        cur = await db.execute("SELECT p.*, u.username, u.first_name, u.custom_nick FROM posts p JOIN users u ON u.id=p.author_id WHERE p.id=? AND p.status='approved'", (post_id,))
        post = await cur.fetchone()
        if not post: raise HTTPException(404)
        
        cur = await db.execute("SELECT c.*, u.username, u.first_name, u.custom_nick FROM comments c JOIN users u ON u.id=c.author_id WHERE c.post_id=? AND c.is_hidden=0 ORDER BY c.created_at", (post_id,))
        comments = [dict(r) for r in await cur.fetchall()]
        
        cur = await db.execute("SELECT value FROM votes WHERE user_id=? AND target_type='post' AND target_id=?", (user.get("id"), post_id))
        vote = await cur.fetchone()
        post = dict(post); post["my_vote"] = vote[0] if vote else 0
    return {"post": post, "comments": comments}

@app.post("/api/comments")
async def create_comment(data: CommentIn, user=Depends(current_user)):
    await ensure_user(user)
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("INSERT INTO comments(post_id,parent_id,author_id,body) VALUES (?,?,?,?)",
                               (data.post_id, data.parent_id, user.get("id"), data.body))
        comment_id = cur.lastrowid
        
        # Уведомление автору поста
        cur = await db.execute("SELECT author_id, title FROM posts WHERE id=?", (data.post_id,))
        post_author = await cur.fetchone()
        if post_author and post_author[0] != user.get("id"):
            msg = f"💬 <b>Новый комментарий!</b>\nК посту: {post_author[1]}\n\nОт: {user.get('first_name')}\n{data.body[:100]}..."
            await send_tg(post_author[0], msg)
        await db.commit()
    return {"id": comment_id}

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

@app.get("/api/profile/{user_id}")
async def get_profile(user_id: int, user=Depends(current_user)):
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM users WHERE id=?", (user_id,))
        u = await cur.fetchone()
        if not u: raise HTTPException(404)
        
        # Динамическая карма
        cur = await db.execute("SELECT SUM(score) FROM posts WHERE author_id=?", (user_id,))
        p_karma = (await cur.fetchone())[0] or 0
        cur = await db.execute("SELECT SUM(score) FROM comments WHERE author_id=?", (user_id,))
        c_karma = (await cur.fetchone())[0] or 0
        
        # Статистика
        cur = await db.execute("SELECT COUNT(*) FROM posts WHERE author_id=?", (user_id,))
        p_count = (await cur.fetchone())[0]
        cur = await db.execute("SELECT title, score FROM posts WHERE author_id=? ORDER BY score DESC LIMIT 1", (user_id,))
        top_post = await cur.fetchone()
        cur = await db.execute("SELECT tag, COUNT(*) as c FROM posts WHERE author_id=? GROUP BY tag ORDER BY c DESC LIMIT 3", (user_id,))
        fav_tags = [r["tag"] for r in await cur.fetchall()]

    return {
        **dict(u), "karma": p_karma + c_karma, "posts_count": p_count,
        "top_post": dict(top_post) if top_post else None, "fav_tags": fav_tags
    }

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

@app.on_event("startup")
async def _startup(): await init_db()

app.mount("/", StaticFiles(directory="static", html=True), name="static")
