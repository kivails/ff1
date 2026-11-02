import json
from fastapi import FastAPI, HTTPException, Depends, Query
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from aiocache import cached, Cache
from aiocache.serializers import JsonSerializer
from database import DB, get_db, init_db
from auth import current_user

app = FastAPI()
BOT_TOKEN = "ТВОЙ_ТОКЕН"
ADMIN_IDS = {123456789}  # твой telegram id

cache = Cache(Cache.MEMORY, serializer=JsonSerializer())

# ============ Вспомогательное ============
async def notify(db, user_id, type_, payload):
    await db.execute(
        "INSERT INTO notifications(user_id,type,payload) VALUES (?,?,?)",
        (user_id, type_, json.dumps(payload))
    )

async def bump_tag(db, tag):
    await db.execute(
        """INSERT INTO tags(name, posts_count) VALUES (?,1)
           ON CONFLICT(name) DO UPDATE SET posts_count = posts_count + 1""",
        (tag,)
    )

async def apply_karma(db, user_id, delta):
    await db.execute("UPDATE users SET karma = karma + ? WHERE id = ?", (delta, user_id))

async def invalidate(prefix: str):
    await cache.clear()   # простой вариант; для продакшена — точечно

# ============ Модели ============
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

class ReportIn(BaseModel):
    target_type: str
    target_id: int
    reason: str = ""

# ============ Посты ============
@app.get("/api/posts")
async def list_posts(
    sort: str = "new",
    tag: str | None = None,
    q: str | None = None,
    page: int = 1,
    limit: int = 20,
    user=Depends(current_user)
):
    if limit > 50: limit = 50
    offset = (page - 1) * limit
    order = {
        "new":  "p.created_at DESC",
        "top":  "p.score DESC, p.created_at DESC",
        "hot":  "(p.score * 1.0 / (julianday('now') - julianday(p.created_at) + 2)) DESC"
    }.get(sort, "p.created_at DESC")

    async with await get_db() as db:
        if q:
            # FTS5 поиск
            cursor = await db.execute(
                """SELECT p.id, p.title, p.tag, p.score, p.views, p.created_at,
                          u.username, u.first_name,
                          (SELECT COUNT(*) FROM comments c WHERE c.post_id=p.id) AS comments
                   FROM posts_fts f
                   JOIN posts p ON p.id = f.rowid
                   JOIN users u ON u.id = p.author_id
                   WHERE posts_fts MATCH ? AND p.is_hidden = 0
                   ORDER BY p.score DESC LIMIT ? OFFSET ?""",
                (q + "*", limit, offset)
            )
        else:
            where = ["p.is_hidden = 0"]
            params = []
            if tag:
                where.append("p.tag = ?")
                params.append(tag)
            params += [limit, offset]
            cursor = await db.execute(
                f"""SELECT p.id, p.title, p.tag, p.score, p.views, p.created_at,
                           u.username, u.first_name,
                           (SELECT COUNT(*) FROM comments c WHERE c.post_id=p.id) AS comments
                    FROM posts p JOIN users u ON u.id=p.author_id
                    WHERE {' AND '.join(where)}
                    ORDER BY {order} LIMIT ? OFFSET ?""",
                params
            )
        rows = [dict(r) for r in await cursor.fetchall()]

    return {"posts": rows, "page": page, "has_more": len(rows) == limit}

@app.get("/api/posts/{post_id}")
async def get_post(post_id: int, user=Depends(current_user)):
    async with await get_db() as db:
        await db.execute("UPDATE posts SET views = views + 1 WHERE id=?", (post_id,))
        await db.commit()

        cur = await db.execute("""
            SELECT p.*, u.username, u.first_name, u.karma as author_karma
            FROM posts p JOIN users u ON u.id=p.author_id
            WHERE p.id=? AND p.is_hidden=0
        """, (post_id,))
        post = await cur.fetchone()
        if not post:
            raise HTTPException(404)

        cur = await db.execute("""
            SELECT c.*, u.username, u.first_name, u.karma as author_karma
            FROM comments c JOIN users u ON u.id=c.author_id
            WHERE c.post_id=? AND c.is_hidden=0
            ORDER BY c.created_at
        """, (post_id,))
        comments = [dict(r) for r in await cur.fetchall()]

        # текущий голос пользователя
        cur = await db.execute(
            "SELECT value FROM votes WHERE user_id=? AND target_type='post' AND target_id=?",
            (user["id"], post_id)
        )
        my_vote = (await cur.fetchone())
        post = dict(post); post["my_vote"] = my_vote[0] if my_vote else 0

        # подписка
        cur = await db.execute(
            "SELECT 1 FROM subscriptions WHERE user_id=? AND post_id=?",
            (user["id"], post_id)
        )
        post["subscribed"] = bool(await cur.fetchone())

    return {"post": post, "comments": comments}

@app.post("/api/posts")
async def create_post(data: PostIn, user=Depends(current_user)):
    if not data.title.strip() or len(data.title) > 200:
        raise HTTPException(400, "bad title")
    if len(data.body) > 10000:
        raise HTTPException(400, "too long")
    async with await get_db() as db:
        cur = await db.execute(
            "INSERT INTO posts(author_id,title,body,tag,image_file_id) VALUES (?,?,?,?,?)",
            (user["id"], data.title, data.body, data.tag, data.image_file_id)
        )
        await bump_tag(db, data.tag)
        await apply_karma(db, user["id"], 2)   # +2 кармы за пост
        await db.commit()
        new_id = cur.lastrowid
    await invalidate("posts")
    return {"id": new_id}

@app.delete("/api/posts/{post_id}")
async def delete_post(post_id: int, user=Depends(current_user)):
    async with await get_db() as db:
        cur = await db.execute("SELECT author_id FROM posts WHERE id=?", (post_id,))
        row = await cur.fetchone()
        if not row: raise HTTPException(404)
        if row["author_id"] != user["id"] and user["id"] not in ADMIN_IDS:
            raise HTTPException(403)
        await db.execute("DELETE FROM posts WHERE id=?", (post_id,))
        await db.commit()
    return {"ok": True}

# ============ Комментарии ============
@app.post("/api/comments")
async def create_comment(data: CommentIn, user=Depends(current_user)):
    if not data.body.strip(): raise HTTPException(400, "empty")
    async with await get_db() as db:
        cur = await db.execute(
            "INSERT INTO comments(post_id,parent_id,author_id,body) VALUES (?,?,?,?)",
            (data.post_id, data.parent_id, user["id"], data.body)
        )
        comment_id = cur.lastrowid
        await apply_karma(db, user["id"], 1)

        # уведомление родителю или автору поста
        target_author = None
        if data.parent_id:
            cur = await db.execute(
                "SELECT author_id FROM comments WHERE id=?", (data.parent_id,))
            r = await cur.fetchone()
            if r: target_author = r["author_id"]
        if not target_author:
            cur = await db.execute(
                "SELECT author_id FROM posts WHERE id=?", (data.post_id,))
            r = await cur.fetchone()
            if r: target_author = r["author_id"]

        if target_author and target_author != user["id"]:
            await notify(db, target_author, "reply", {
                "post_id": data.post_id, "comment_id": comment_id,
                "from": user.get("first_name") or user.get("username"),
                "preview": data.body[:100]
            })

        # уведомления подписчикам
        cur = await db.execute(
            "SELECT user_id FROM subscriptions WHERE post_id=?", (data.post_id,))
        for r in await cur.fetchall():
            if r["user_id"] not in (user["id"], target_author):
                await notify(db, r["user_id"], "reply", {
                    "post_id": data.post_id, "comment_id": comment_id,
                    "from": user.get("first_name"), "preview": data.body[:100]
                })

        await db.commit()
    return {"id": comment_id}

# ============ Голоса ============
@app.post("/api/vote")
async def vote(data: VoteIn, user=Depends(current_user)):
    if data.target_type not in ("post", "comment") or data.value not in (1, -1, 0):
        raise HTTPException(400)
    table = "posts" if data.target_type == "post" else "comments"

    async with await get_db() as db:
        cur = await db.execute(f"SELECT author_id, score FROM {table} WHERE id=?",
                               (data.target_id,))
        target = await cur.fetchone()
        if not target: raise HTTPException(404)
        author_id = target["author_id"]

        cur = await db.execute(
            "SELECT value FROM votes WHERE user_id=? AND target_type=? AND target_id=?",
            (user["id"], data.target_type, data.target_id))
        old = await cur.fetchone()
        old_v = old[0] if old else 0
        delta = data.value - old_v
        if delta == 0: return {"score": target["score"]}

        if data.value == 0:
            await db.execute(
                "DELETE FROM votes WHERE user_id=? AND target_type=? AND target_id=?",
                (user["id"], data.target_type, data.target_id))
        else:
            await db.execute("""
                INSERT INTO votes(user_id,target_type,target_id,value) VALUES (?,?,?,?)
                ON CONFLICT(user_id,target_type,target_id) DO UPDATE SET value=excluded.value
            """, (user["id"], data.target_type, data.target_id, data.value))

        await db.execute(f"UPDATE {table} SET score=score+? WHERE id=?",
                         (delta, data.target_id))

        # карма автору (только при upvote/downvote, не за отмену)
        if author_id != user["id"]:
            await apply_karma(db, author_id, delta)

        await db.commit()
        cur = await db.execute(f"SELECT score FROM {table} WHERE id=?", (data.target_id,))
        new_score = (await cur.fetchone())["score"]
    return {"score": new_score, "my_vote": data.value}

# ============ Поиск ============
@app.get("/api/search")
async def search(q: str = Query(..., min_length=2), user=Depends(current_user)):
    return await list_posts(sort="top", q=q, user=user)

@app.get("/api/tags")
async def tags(user=Depends(current_user)):
    async with await get_db() as db:
        cur = await db.execute("SELECT name, posts_count FROM tags ORDER BY posts_count DESC LIMIT 30")
        return [dict(r) for r in await cur.fetchall()]

@app.get("/api/users/{user_id}")
async def user_profile(user_id: int, user=Depends(current_user)):
    async with await get_db() as db:
        cur = await db.execute(
            "SELECT id,username,first_name,karma,created_at FROM users WHERE id=?",
            (user_id,))
        u = await cur.fetchone()
        if not u: raise HTTPException(404)
        cur = await db.execute(
            "SELECT COUNT(*) as c FROM posts WHERE author_id=? AND is_hidden=0", (user_id,))
        posts_count = (await cur.fetchone())["c"]
    return {**dict(u), "posts_count": posts_count}

# ============ Жалобы ============
@app.post("/api/report")
async def report(data: ReportIn, user=Depends(current_user)):
    if data.target_type not in ("post","comment"): raise HTTPException(400)
    async with await get_db() as db:
        await db.execute(
            "INSERT INTO reports(reporter_id,target_type,target_id,reason) VALUES (?,?,?,?)",
            (user["id"], data.target_type, data.target_id, data.reason))
        # авто-скрытие после 5 жалоб
        cur = await db.execute(
            "SELECT COUNT(*) c FROM reports WHERE target_type=? AND target_id=? AND resolved=0",
            (data.target_type, data.target_id))
        cnt = (await cur.fetchone())["c"]
        if cnt >= 5:
            table = "posts" if data.target_type == "post" else "comments"
            await db.execute(f"UPDATE {table} SET is_hidden=1 WHERE id=?", (data.target_id,))
        await db.commit()
    return {"ok": True}

@app.get("/api/reports")
async def list_reports(user=Depends(current_user)):
    if user["id"] not in ADMIN_IDS: raise HTTPException(403)
    async with await get_db() as db:
        cur = await db.execute("""
            SELECT r.*, u.username FROM reports r
            JOIN users u ON u.id=r.reporter_id
            WHERE r.resolved=0 ORDER BY r.created_at DESC LIMIT 100
        """)
        return [dict(r) for r in await cur.fetchall()]

@app.post("/api/reports/{report_id}/resolve")
async def resolve_report(report_id: int, action: str = "dismiss",
                        user=Depends(current_user)):
    if user["id"] not in ADMIN_IDS: raise HTTPException(403)
    async with await get_db() as db:
        cur = await db.execute("SELECT * FROM reports WHERE id=?", (report_id,))
        r = await cur.fetchone()
        if not r: raise HTTPException(404)
        if action == "hide":
            table = "posts" if r["target_type"]=="post" else "comments"
            await db.execute(f"UPDATE {table} SET is_hidden=1 WHERE id=?", (r["target_id"],))
        await db.execute("UPDATE reports SET resolved=1 WHERE id=?", (report_id,))
        await db.commit()
    return {"ok": True}

# ============ Уведомления ============
@app.get("/api/notifications")
async def notifications(user=Depends(current_user)):
    async with await get_db() as db:
        cur = await db.execute(
            """SELECT * FROM notifications WHERE user_id=?
               ORDER BY created_at DESC LIMIT 50""", (user["id"],))
        rows = [dict(r) for r in await cur.fetchall()]
        for r in rows:
            r["payload"] = json.loads(r["payload"])
    return rows

@app.post("/api/notifications/read")
async def mark_read(user=Depends(current_user)):
    async with await get_db() as db:
        await db.execute("UPDATE notifications SET is_read=1 WHERE user_id=?", (user["id"],))
        await db.commit()
    return {"ok": True}

@app.get("/api/notifications/count")
async def notif_count(user=Depends(current_user)):
    async with await get_db() as db:
        cur = await db.execute(
            "SELECT COUNT(*) c FROM notifications WHERE user_id=? AND is_read=0",
            (user["id"],))
        return {"count": (await cur.fetchone())["c"]}

# ============ Подписки ============
@app.post("/api/subscribe/{post_id}")
async def subscribe(post_id: int, user=Depends(current_user)):
    async with await get_db() as db:
        cur = await db.execute(
            "SELECT 1 FROM subscriptions WHERE user_id=? AND post_id=?",
            (user["id"], post_id))
        exists = await cur.fetchone()
        if exists:
            await db.execute(
                "DELETE FROM subscriptions WHERE user_id=? AND post_id=?",
                (user["id"], post_id))
            subscribed = False
        else:
            await db.execute(
                "INSERT INTO subscriptions(user_id,post_id) VALUES (?,?)",
                (user["id"], post_id))
            subscribed = True
        await db.commit()
    return {"subscribed": subscribed}

# ============ Загрузка изображений ============
import httpx
@app.post("/api/upload")
async def upload_image(file: bytes = None, user=Depends(current_user)):
    # Принимаем multipart через UploadFile (упрощённо)
    raise HTTPException(400, "use /api/upload_file")

from fastapi import UploadFile, File
@app.post("/api/upload_file")
async def upload_file(file: UploadFile = File(...), user=Depends(current_user)):
    """Загружает файл в Telegram-чат пользователя и возвращает file_id."""
    if file.content_type not in ("image/jpeg","image/png","image/webp"):
        raise HTTPException(400, "only images")
    content = await file.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(400, "max 5MB")

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
            data={"chat_id": user["id"]},
            files={"photo": ("upload.jpg", content, "image/jpeg")}
        )
        data = r.json()
        if not data.get("ok"):
            raise HTTPException(500, data)
        file_id = data["result"]["photo"][-1]["file_id"]
        # сразу удалим сообщение
        await client.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/deleteMessage",
            data={"chat_id": user["id"], "message_id": data["result"]["message_id"]}
        )
    return {"file_id": file_id}

# ============ Мои посты ============
@app.get("/api/my/posts")
async def my_posts(user=Depends(current_user)):
    async with await get_db() as db:
        cur = await db.execute("""
            SELECT id,title,tag,score,views,is_hidden,created_at
            FROM posts WHERE author_id=? ORDER BY created_at DESC
        """, (user["id"],))
        return [dict(r) for r in await cur.fetchall()]

# ============ Старт ============
@app.on_event("startup")
async def _startup():
    await init_db()

app.mount("/", StaticFiles(directory="static", html=True), name="static")

from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],      # разрешаем всем
    allow_methods=["*"],      # любые действия
    allow_headers=["*"],      # любые заголовки
)
