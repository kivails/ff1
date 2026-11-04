import json, os, httpx, datetime, random
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
APP_URL = os.environ.get("APP_URL", "https://твой-сайт.onrender.com")

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

async def ensure_user(user):
    async with aiosqlite.connect(DB) as db:
        await db.execute("INSERT OR IGNORE INTO users(id, username, first_name) VALUES (?,?,?)", (user.get("id"), user.get("username"), user.get("first_name")))
        await db.execute("UPDATE users SET last_seen = CURRENT_TIMESTAMP WHERE id = ?", (user.get("id"),))
        await db.commit()

async def send_tg(chat_id, text):
    async with httpx.AsyncClient() as client:
        await client.post(f"{TG_API}/sendMessage", json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"})

class PostIn(BaseModel):
    title: str; body: str; tags: str = "general"; image_file_id: str | None = None
    is_anonymous: bool = False; is_adult: bool = False; style: str = "default"; mentioned_user: int | None = None

class CommentIn(BaseModel):
    post_id: int; parent_id: int | None = None; body: str; file_id: str | None = None

class VoteIn(BaseModel):
    target_type: str; target_id: int; value: int

class ReactionIn(BaseModel):
    target_type: str; target_id: int; emoji: str

class ProfileUpdate(BaseModel):
    custom_nick: str | None = None
    bio: str | None = None
    theme: str | None = None
    banner: str | None = None

class GiftIn(BaseModel):
    to_id: int
    gift: str
    description: str = ""

class SubscribeIn(BaseModel):
    target_id: int

class BetIn(BaseModel):
    bet: int

class ShareIn(BaseModel):
    post_id: int

class ReportIn(BaseModel):
    target_type: str
    target_id: int
    reason: str

class PollIn(BaseModel):
    post_id: int
    question: str
    options: list[str]

class PollVoteIn(BaseModel):
    poll_id: int
    option_index: int

class SaveIn(BaseModel):
    post_id: int

class RedeemIn(BaseModel):
    code: str

class BoostIn(BaseModel):
    post_id: int
    boost_type: str  # "1m", "10m", "30m"

class StyleIn(BaseModel):
    post_id: int
    style: str

@app.get("/ping")
async def ping(): return {"status": "alive"}

# --- ПЛЕЙЛИСТ ---
@app.get("/api/playlist")
async def get_playlist():
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("SELECT value FROM settings WHERE key='playlist'")
        row = await cur.fetchone()
    return json.loads(row[0]) if row and row[0] else []

@app.get("/api/music/{index}")
async def get_music(index: int):
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("SELECT value FROM settings WHERE key='playlist'")
        row = await cur.fetchone()
    playlist = json.loads(row[0]) if row and row[0] else []
    if index >= len(playlist): raise HTTPException(404)
    file_id = playlist[index]
    async with httpx.AsyncClient() as c:
        r = await c.get(f"{TG_API}/getFile?file_id={file_id}")
        if not r.json().get("ok"): raise HTTPException(500)
        path = r.json()["result"]["file_path"]
        file_resp = await c.get(f"https://api.telegram.org/file/bot{BOT_TOKEN}/{path}", timeout=60)
    return StreamingResponse(iter([file_resp.content]), media_type="audio/mpeg")

# --- ПОСТЫ ---
@app.get("/api/posts")
async def list_posts(sort: str = "new", q: str | None = None, user=Depends(current_user)):
    await ensure_user(user)
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        query = """SELECT p.*, u.username, u.first_name, u.custom_nick, u.badge,
                   (SELECT COUNT(*) FROM comments c WHERE c.post_id=p.id) AS comments
                   FROM posts p JOIN users u ON u.id=p.author_id WHERE p.status='approved' AND p.is_hidden=0"""
        params = []
        if q: query += " AND p.tags LIKE ?"; params.append(f"%{q}%")
        if sort == "day_top": query += " AND p.created_at >= date('now', '-1 day') ORDER BY p.boost_until DESC, p.score DESC"
        else: query += " ORDER BY p.boost_until DESC, p.created_at DESC"
        cur = await db.execute(query + " LIMIT 50", params)
        posts = [dict(r) for r in await cur.fetchall()]
        for p in posts:
            cur = await db.execute("SELECT emoji, COUNT(*) as c FROM reactions WHERE target_type='post' AND target_id=? GROUP BY emoji", (p["id"],))
            p["reactions"] = {r["emoji"]: r["c"] for r in await cur.fetchall()}
    return {"posts": posts}

@app.get("/api/posts/subscriptions")
async def subscribed_posts(user=Depends(current_user)):
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("""SELECT p.*, u.username, u.first_name, u.custom_nick, u.badge FROM posts p 
                                  JOIN users u ON u.id=p.author_id 
                                  WHERE p.author_id IN (SELECT target_id FROM subscriptions WHERE user_id=?)
                                  AND p.status='approved' ORDER BY p.created_at DESC LIMIT 50""", (user.get("id"),))
        return [dict(r) for r in await cur.fetchall()]

@app.post("/api/posts")
async def create_post(data: PostIn, user=Depends(current_user)):
    await ensure_user(user)
    async with aiosqlite.connect(DB) as db:
        tags_str = ', '.join([t.strip().replace('#', '') for t in data.tags.split(',') if t.strip()][:3]) or 'general'
        status = 'approved' if user.get("id") in ADMIN_IDS else 'pending'
        cur = await db.execute("""INSERT INTO posts(author_id,title,body,tags,image_file_id,status,is_anonymous,is_adult,style,mentioned_user) 
                                  VALUES (?,?,?,?,?,?,?,?,?,?)""", 
                               (user.get("id"), data.title, data.body, tags_str, data.image_file_id, status, 
                                1 if data.is_anonymous else 0, 1 if data.is_adult else 0, data.style, data.mentioned_user))
        post_id = cur.lastrowid
        await db.commit()
        
        if data.mentioned_user:
            await db.execute("INSERT INTO notifications(user_id, type, payload) VALUES (?,?,?)",
                             (data.mentioned_user, "mention", json.dumps({"post_id": post_id, "from": user.get("first_name")})))
            await db.commit()
            try:
                await send_tg(data.mentioned_user, f"👋 Тебя упомянули в посте!\n\n<b>{data.title}</b>\n\nОт: {user.get('first_name')}\n🔗 {APP_URL}/#post/{post_id}")
            except: pass
        
    if status == 'pending':
        for admin in ADMIN_IDS:
            kb = {"inline_keyboard": [[{"text": "✅ Одобрить", "callback_data": f"mod_ok_{post_id}"},{"text": "❌ Отклонить", "callback_data": f"mod_no_{post_id}"}]]}
            author = "Аноним" if data.is_anonymous else user.get('first_name')
            caption = f"🛡️ <b>Пост на модерацию!</b>\nОт: {author}\n\n<b>{data.title}</b>\n{data.body[:200]}...\n\nТеги: {tags_str}"
            if data.is_adult: caption += "\n\n⚠️ <b>18+</b>"
            async with httpx.AsyncClient() as client:
                if data.image_file_id: await client.post(f"{TG_API}/sendPhoto", data={"chat_id": admin, "photo": data.image_file_id, "caption": caption, "parse_mode": "HTML", "reply_markup": json.dumps(kb)})
                else: await client.post(f"{TG_API}/sendMessage", data={"chat_id": admin, "text": caption, "parse_mode": "HTML", "reply_markup": json.dumps(kb)})
    return {"id": post_id, "status": status}

@app.delete("/api/posts/{post_id}")
async def delete_post(post_id: int, user=Depends(current_user)):
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("SELECT author_id FROM posts WHERE id=?", (post_id,))
        row = await cur.fetchone()
        if not row or (row[0] != user.get("id") and user.get("id") not in ADMIN_IDS): raise HTTPException(403)
        await db.execute("DELETE FROM posts WHERE id=?", (post_id,))
        await db.commit()
    return {"ok": True}

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
        cur = await db.execute("SELECT 1 FROM saved_posts WHERE user_id=? AND post_id=?", (user.get("id"), post_id))
        post["is_saved"] = bool(await cur.fetchone())
    return {"post": post, "comments": comments}

@app.post("/api/comments")
async def create_comment(data: CommentIn, user=Depends(current_user)):
    await ensure_user(user)
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("SELECT created_at FROM comments WHERE author_id=? ORDER BY id DESC LIMIT 1", (user.get("id"),))
        last = await cur.fetchone()
        if last and (datetime.datetime.utcnow() - datetime.datetime.fromisoformat(last[0])).total_seconds() < 30: raise HTTPException(400, "КД 30 сек!")
        body = data.body + (f"\n[sticker]{data.file_id}[/sticker]" if data.file_id else "")
        cur = await db.execute("INSERT INTO comments(post_id,parent_id,author_id,body) VALUES (?,?,?,?)", (data.post_id, data.parent_id, user.get("id"), body))
        await db.commit()
        cur = await db.execute("SELECT author_id, title FROM posts WHERE id=?", (data.post_id,))
        post_author = await cur.fetchone()
        if post_author and post_author[0] != user.get("id"):
            try: await send_tg(post_author[0], f"💬 <b>Новый комментарий!</b>\nК посту: {post_author[1]}\n\nОт: {user.get('first_name')}\n{data.body[:100]}...")
            except: pass
    return {"id": cur.lastrowid}

@app.post("/api/vote")
async def vote(data: VoteIn, user=Depends(current_user)):
    await ensure_user(user)
    async with aiosqlite.connect(DB) as db:
        table = "posts" if data.target_type == "post" else "comments"
        cur = await db.execute("SELECT value FROM votes WHERE user_id=? AND target_type=? AND target_id=?", (user.get("id"), data.target_type, data.target_id))
        old = await cur.fetchone()
        delta = data.value - (old[0] if old else 0)
        if data.value == 0: await db.execute("DELETE FROM votes WHERE user_id=? AND target_type=? AND target_id=?", (user.get("id"), data.target_type, data.target_id))
        else: await db.execute("INSERT INTO votes VALUES (?,?,?,?) ON CONFLICT DO UPDATE SET value=excluded.value", (user.get("id"), data.target_type, data.target_id, data.value))
        await db.execute(f"UPDATE {table} SET score=score+? WHERE id=?", (delta, data.target_id))
        await db.commit()
    return {"ok": True}

@app.post("/api/react")
async def react(data: ReactionIn, user=Depends(current_user)):
    await ensure_user(user)
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("SELECT emoji FROM reactions WHERE user_id=? AND target_type=? AND target_id=?", (user.get("id"), data.target_type, data.target_id))
        my = [r[0] for r in await cur.fetchall()]
        if data.emoji in my: await db.execute("DELETE FROM reactions WHERE user_id=? AND target_type=? AND target_id=? AND emoji=?", (user.get("id"), data.target_type, data.target_id, data.emoji))
        else:
            if len(my) >= (3 if user.get("id") in ADMIN_IDS else 1): raise HTTPException(400, "Лимит!")
            await db.execute("INSERT INTO reactions VALUES (?,?,?,?)", (user.get("id"), data.target_type, data.target_id, data.emoji))
        await db.commit()
    return {"ok": True}

@app.get("/api/custom_reactions")
async def get_custom_reactions():
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM custom_reactions")
        return [dict(r) for r in await cur.fetchall()]

# --- ПОДПИСКИ ---
@app.post("/api/subscribe")
async def subscribe(data: SubscribeIn, user=Depends(current_user)):
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("SELECT 1 FROM subscriptions WHERE user_id=? AND target_id=?", (user.get("id"), data.target_id))
        if await cur.fetchone():
            await db.execute("DELETE FROM subscriptions WHERE user_id=? AND target_id=?", (user.get("id"), data.target_id))
            await db.commit()
            return {"subscribed": False}
        await db.execute("INSERT INTO subscriptions VALUES (?,?)", (user.get("id"), data.target_id))
        await db.commit()
    return {"subscribed": True}

# --- ПРОФИЛЬ ---
@app.get("/api/profile/{user_id}")
async def get_profile(user_id: int, user=Depends(current_user)):
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM users WHERE id=?", (user_id,))
        u = await cur.fetchone()
        if not u: raise HTTPException(404)
        cur = await db.execute("SELECT SUM(score) FROM posts WHERE author_id=?", (user_id,))
        p = (await cur.fetchone())[0] or 0
        cur = await db.execute("SELECT SUM(score) FROM comments WHERE author_id=?", (user_id,))
        c = (await cur.fetchone())[0] or 0
        cur = await db.execute("SELECT id, title FROM posts WHERE author_id=? ORDER BY score DESC LIMIT 1", (user_id,))
        top = await cur.fetchone()
        cur = await db.execute("SELECT ach_name FROM achievements WHERE user_id=?", (user_id,))
        achs = [r["ach_name"] for r in await cur.fetchall()]
        cur = await db.execute("""SELECT g.gift_name, g.description, u.custom_nick, u.first_name FROM gifts g JOIN users u ON u.id=g.from_id WHERE g.to_id=?""", (user_id,))
        gifts = [{"name": r["gift_name"], "desc": r["description"], "from": r["custom_nick"] or r["first_name"]} for r in await cur.fetchall()]
        cur = await db.execute("SELECT 1 FROM subscriptions WHERE user_id=? AND target_id=?", (user.get("id"), user_id))
        is_subscribed = bool(await cur.fetchone())
        cur = await db.execute("SELECT COUNT(*) FROM strikes WHERE user_id=?", (user_id,))
        strikes_count = (await cur.fetchone())[0]
    return {**dict(u), "karma": p + c, "level": (p + c) // 10, "top_post": dict(top) if top else None, "achievements": achs, "gifts": gifts, "is_subscribed": is_subscribed, "strikes": strikes_count}

@app.post("/api/profile")
async def update_profile(data: ProfileUpdate, user=Depends(current_user)):
    await ensure_user(user)
    async with aiosqlite.connect(DB) as db:
        if data.custom_nick: await db.execute("UPDATE users SET custom_nick=? WHERE id=?", (data.custom_nick, user.get("id")))
        if data.bio is not None: await db.execute("UPDATE users SET bio=? WHERE id=?", (data.bio, user.get("id")))
        if data.theme: await db.execute("UPDATE users SET theme=? WHERE id=?", (data.theme, user.get("id")))
        if data.banner: await db.execute("UPDATE users SET banner=? WHERE id=?", (data.banner, user.get("id")))
        await db.commit()
    return {"ok": True}

# --- ИГРЫ ---
@app.post("/api/games/roulette")
async def game_roulette(user=Depends(current_user)):
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("SELECT last_roulette FROM users WHERE id=?", (user.get("id"),))
        last = await cur.fetchone()
        now = datetime.datetime.utcnow()
        if last and last[0] and (now - datetime.datetime.fromisoformat(last[0])).total_seconds() < 86400:
            raise HTTPException(400, "Рулетка раз в 24 часа!")
        win = random.choice([0, 1, 2, 5, 10, 50])
        await db.execute("UPDATE users SET crystals = crystals + ?, last_roulette=? WHERE id=?", (win, now.isoformat(), user.get("id")))
        await db.execute("INSERT INTO games_log(user_id, game, win) VALUES (?,?,?)", (user.get("id"), "roulette", win))
        await db.commit()
    return {"win": win}

@app.post("/api/games/rocket")
async def game_rocket(data: BetIn, user=Depends(current_user)):
    if data.bet < 5: raise HTTPException(400, "Мин. ставка 5 💎")
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("SELECT crystals FROM users WHERE id=?", (user.get("id"),))
        if (await cur.fetchone())[0] < data.bet: raise HTTPException(400, "Мало кристаллов!")
        crash = random.uniform(1.1, 5.0)
        win = int(data.bet * crash)
        await db.execute("UPDATE users SET crystals = crystals + ? WHERE id=?", (win - data.bet, user.get("id")))
        await db.execute("INSERT INTO games_log(user_id, game, win) VALUES (?,?,?)", (user.get("id"), "rocket", win - data.bet))
        await db.commit()
    return {"crash": round(crash, 2), "win": win}

@app.post("/api/games/case")
async def game_case(user=Depends(current_user)):
    cost = 20
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("SELECT crystals FROM users WHERE id=?", (user.get("id"),))
        if (await cur.fetchone())[0] < cost: raise HTTPException(400, "Мало кристаллов!")
        await db.execute("UPDATE users SET crystals = crystals - ? WHERE id=?", (cost, user.get("id")))
        prize = random.choice(["none", "crystals_10", "crystals_50", "frame_gold", "frame_fire"])
        if prize == "crystals_10": await db.execute("UPDATE users SET crystals = crystals + 10 WHERE id=?", (user.get("id"),))
        elif prize == "crystals_50": await db.execute("UPDATE users SET crystals = crystals + 50 WHERE id=?", (user.get("id"),))
        elif prize == "frame_gold": await db.execute("UPDATE users SET frame='gold' WHERE id=?", (user.get("id"),))
        elif prize == "frame_fire": await db.execute("UPDATE users SET frame='fire' WHERE id=?", (user.get("id"),))
        await db.execute("INSERT INTO games_log(user_id, game, win) VALUES (?,?,?)", (user.get("id"), "case", 0))
        await db.commit()
    return {"prize": prize}

# --- МАГАЗИН ---
@app.post("/api/buy_frame")
async def buy_frame(frame: str, user=Depends(current_user)):
    await ensure_user(user)
    costs = {"gold": 50, "fire": 100, "sakura": 150, "anime": 200, "neon": 250}
    if frame not in costs: raise HTTPException(400)
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("SELECT crystals FROM users WHERE id=?", (user.get("id"),))
        if (await cur.fetchone())[0] < costs[frame]: raise HTTPException(400, "Мало кристаллов!")
        await db.execute("UPDATE users SET crystals = crystals - ?, frame = ? WHERE id=?", (costs[frame], frame, user.get("id")))
        await db.commit()
    return {"ok": True}

@app.get("/api/banners")
async def get_banners():
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM banners")
        return [dict(r) for r in await cur.fetchall()]

@app.post("/api/buy_banner")
async def buy_banner(banner_id: int, user=Depends(current_user)):
    await ensure_user(user)
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("SELECT price, image_url FROM banners WHERE id=?", (banner_id,))
        row = await cur.fetchone()
        if not row: raise HTTPException(404)
        price, img = row
        cur = await db.execute("SELECT crystals FROM users WHERE id=?", (user.get("id"),))
        if (await cur.fetchone())[0] < price: raise HTTPException(400, "Мало кристаллов!")
        await db.execute("UPDATE users SET crystals = crystals - ?, banner = ? WHERE id=?", (price, img, user.get("id")))
        await db.commit()
    return {"ok": True}

@app.post("/api/buy_gift")
async def buy_gift(data: GiftIn, user=Depends(current_user)):
    await ensure_user(user)
    costs = {"heart": 10, "star": 30, "crown": 100, "rose": 50, "diamond": 200}
    if data.gift not in costs: raise HTTPException(400)
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("SELECT crystals FROM users WHERE id=?", (user.get("id"),))
        if (await cur.fetchone())[0] < costs[data.gift]: raise HTTPException(400, "Мало кристаллов!")
        await db.execute("UPDATE users SET crystals = crystals - ? WHERE id=?", (costs[data.gift], user.get("id")))
        await db.execute("INSERT INTO gifts(from_id, to_id, gift_name, description) VALUES (?, ?, ?, ?)", (user.get("id"), data.to_id, data.gift, data.description))
        await db.commit()
    return {"ok": True}

@app.get("/api/support")
async def get_support():
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("SELECT value FROM settings WHERE key='support_link'")
        row = await cur.fetchone()
    return {"link": row[0] if row else "https://t.me/kvails"}

# --- ЖАЛОБЫ, СТРАЙКИ, ПРОМО, СОХРАНЕНИЯ, РЕПОСТЫ ---
@app.post("/api/report")
async def report(data: ReportIn, user=Depends(current_user)):
    async with aiosqlite.connect(DB) as db:
        await db.execute("INSERT INTO reports(reporter_id, target_type, target_id, reason) VALUES (?,?,?,?)",
                         (user.get("id"), data.target_type, data.target_id, data.reason))
        await db.commit()
    for admin in ADMIN_IDS:
        try: await send_tg(admin, f"🚩 Жалоба на {data.target_type} {data.target_id}\nПричина: {data.reason}\nОт: {user.get('id')}")
        except: pass
    return {"ok": True}

@app.post("/api/redeem")
async def redeem(data: RedeemIn, user=Depends(current_user)):
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("SELECT value FROM settings WHERE key=?", (f"promo_{data.code}",))
        row = await cur.fetchone()
        if not row: raise HTTPException(404, "Неверный промокод")
        promo = json.loads(row[0])
        if promo["used"] >= promo["limit"]: raise HTTPException(400, "Лимит исчерпан")
        cur = await db.execute("SELECT 1 FROM promo_uses WHERE user_id=? AND code=?", (user.get("id"), data.code))
        if await cur.fetchone(): raise HTTPException(400, "Уже активирован")
        await db.execute("UPDATE users SET crystals = crystals + ? WHERE id=?", (promo["amount"], user.get("id")))
        await db.execute("INSERT INTO promo_uses(user_id, code) VALUES (?,?)", (user.get("id"), data.code))
        promo["used"] += 1
        await db.execute("UPDATE settings SET value=? WHERE key=?", (json.dumps(promo), f"promo_{data.code}"))
        await db.commit()
    return {"amount": promo["amount"]}

@app.post("/api/save_post")
async def save_post(data: SaveIn, user=Depends(current_user)):
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("SELECT 1 FROM saved_posts WHERE user_id=? AND post_id=?", (user.get("id"), data.post_id))
        if await cur.fetchone():
            await db.execute("DELETE FROM saved_posts WHERE user_id=? AND post_id=?", (user.get("id"), data.post_id))
            await db.commit()
            return {"saved": False}
        await db.execute("INSERT INTO saved_posts VALUES (?,?)", (user.get("id"), data.post_id))
        await db.commit()
    return {"saved": True}

@app.get("/api/saved")
async def get_saved(user=Depends(current_user)):
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("""SELECT p.*, u.custom_nick, u.username FROM posts p 
                                  JOIN saved_posts sp ON sp.post_id = p.id 
                                  JOIN users u ON u.id = p.author_id 
                                  WHERE sp.user_id=? ORDER BY p.created_at DESC""", (user.get("id"),))
        return [dict(r) for r in await cur.fetchall()]

@app.post("/api/repost")
async def repost(data: SaveIn, user=Depends(current_user)):
    async with aiosqlite.connect(DB) as db:
        await db.execute("INSERT INTO reposts(user_id, post_id) VALUES (?,?)", (user.get("id"), data.post_id))
        await db.commit()
    return {"ok": True}

@app.post("/api/share")
async def share(data: ShareIn, user=Depends(current_user)):
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("SELECT title, body, tags FROM posts WHERE id=?", (data.post_id,))
        post = await cur.fetchone()
    if not post: raise HTTPException(404)
    return {"title": post[0], "body": post[1][:300], "tags": post[2], "url": f"{APP_URL}/#post/{data.post_id}"}

# --- БУСТЫ ---
@app.post("/api/boost")
async def boost_post(data: BoostIn, user=Depends(current_user)):
    durations = {"1m": 60, "10m": 600, "30m": 1800}
    prices = {"1m": 30, "10m": 200, "30m": 500}
    if data.boost_type not in durations: raise HTTPException(400)
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("SELECT crystals FROM users WHERE id=?", (user.get("id"),))
        if (await cur.fetchone())[0] < prices[data.boost_type]: raise HTTPException(400, "Мало кристаллов!")
        until = (datetime.datetime.utcnow() + datetime.timedelta(seconds=durations[data.boost_type])).isoformat()
        await db.execute("UPDATE users SET crystals = crystals - ? WHERE id=?", (prices[data.boost_type], user.get("id")))
        await db.execute("UPDATE posts SET boost_until = ? WHERE id=? AND author_id=?", (until, data.post_id, user.get("id")))
        await db.commit()
    return {"ok": True, "until": until}

# --- ОПРОСЫ ---
@app.post("/api/poll")
async def create_poll(data: PollIn, user=Depends(current_user)):
    async with aiosqlite.connect(DB) as db:
        await db.execute("INSERT INTO polls(post_id, question, options) VALUES (?,?,?)",
                         (data.post_id, data.question, json.dumps(data.options)))
        await db.commit()
    return {"ok": True}

@app.post("/api/poll/vote")
async def vote_poll(data: PollVoteIn, user=Depends(current_user)):
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("SELECT 1 FROM poll_votes WHERE user_id=? AND poll_id=?", (user.get("id"), data.poll_id))
        if await cur.fetchone(): raise HTTPException(400, "Ты уже голосовал")
        await db.execute("INSERT INTO poll_votes VALUES (?,?,?)", (user.get("id"), data.poll_id, data.option_index))
        await db.commit()
    return {"ok": True}

# --- ФАЙЛЫ ---
@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...), user=Depends(current_user)):
    content = await file.read()
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{TG_API}/sendDocument", data={"chat_id": user.get("id")}, files={"document": ("file.gif", content)})
        res = r.json()
        if not res.get("ok"): raise HTTPException(500)
        await client.post(f"{TG_API}/deleteMessage", json={"chat_id": user.get("id"), "message_id": res["result"]["message_id"]})
    return {"file_id": res["result"]["document"]["file_id"]}

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

@app.get("/api/sticker/{file_id}")
async def get_sticker(file_id: str):
    async with httpx.AsyncClient() as c:
        r = await c.get(f"{TG_API}/getFile?file_id={file_id}")
        if not r.json().get("ok"): raise HTTPException(404)
        path = r.json()["result"]["file_path"]
        img = await c.get(f"https://api.telegram.org/file/bot{BOT_TOKEN}/{path}")
    return StreamingResponse(iter([img.content]), media_type="image/webp")

@app.get("/api/avatar/{file_id}")
async def get_avatar(file_id: str):
    async with httpx.AsyncClient() as c:
        r = await c.get(f"{TG_API}/getFile?file_id={file_id}")
        if not r.json().get("ok"): raise HTTPException(404)
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
