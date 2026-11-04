import os, asyncio, httpx, random, json, datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import WebAppInfo, MenuButtonCommands
from aiogram.utils.keyboard import InlineKeyboardBuilder
import aiosqlite
from database import DB

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
APP_URL = os.environ.get("APP_URL", "https://твой-сайт.onrender.com")
ADMIN_IDS = {5024935475}

bot = Bot(BOT_TOKEN)
dp = Dispatcher()

async def keep_alive():
    while True:
        try:
            async with httpx.AsyncClient() as client: 
                await client.get(f"{APP_URL}/ping")
        except: 
            pass
        await asyncio.sleep(300)

async def get_avatar_file_id(user_id: int) -> str | None:
    try:
        photos = await bot.get_user_profile_photos(user_id, limit=1)
        if photos.total_count > 0:
            return photos.photos[0][-1].file_id
    except Exception:
        pass
    return None

async def ensure_user_row(user_id, username, first_name):
    async with aiosqlite.connect(DB) as db:
        await db.execute("INSERT OR IGNORE INTO users(id, username, first_name) VALUES (?,?,?)", (user_id, username, first_name))
        await db.execute("UPDATE users SET last_seen = CURRENT_TIMESTAMP WHERE id = ?", (user_id,))
        await db.commit()

@dp.message(CommandStart())
async def start_cmd(message: types.Message):
    avatar_id = await get_avatar_file_id(message.from_user.id)
    await ensure_user_row(message.from_user.id, message.from_user.username, message.from_user.first_name)
    if avatar_id:
        async with aiosqlite.connect(DB) as db:
            await db.execute("UPDATE users SET avatar = ? WHERE id = ?", (avatar_id, message.from_user.id))
            await db.commit()
    GIF_URL = "https://media.giphy.com/media/VbnUQpnihPSIgIXuZv/giphy.gif"
    kb = InlineKeyboardBuilder()
    kb.button(text="📖 Открыть RaReads", web_app=WebAppInfo(url=APP_URL))
    await message.answer_animation(animation=GIF_URL, caption=f"Привет, <b>{message.from_user.first_name}</b>! ⛩️\n\nДобро пожаловать в RaReads!", parse_mode="HTML", reply_markup=kb.as_markup())

@dp.message(Command("support"))
async def support_cmd(message: types.Message):
    await message.answer("🆘 Поддержка: @kvails (https://t.me/kvails)")

@dp.message(Command("style_help"))
async def style_help_cmd(message: types.Message):
    await message.answer("🎨 Украшения поста настраиваются в приложении при создании поста.")

@dp.message(Command("admin"))
async def admin_cmd(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return
    await message.answer(
        "🛡️ Админ-команды:\n"
        "/stats — статистика\n"
        "/badge <id> <текст> — бейдж\n"
        "/ban <id> — бан\n"
        "/freeze <id> — заморозка\n"
        "/strike <id> <причина> — страйк\n"
        "/give_crystals <id> <сумма>\n"
        "/add_banner <название> <цена> <url>\n"
        "/remove_banner <id>\n"
        "/add_promo <код> <сумма> <лимит>\n"
        "/broadcast <текст>\n"
        "/remove_track <номер>"
    )

@dp.message(Command("stats"))
async def stats_cmd(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("SELECT COUNT(*) FROM users"); u = (await cur.fetchone())[0]
        cur = await db.execute("SELECT COUNT(*) FROM posts"); p = (await cur.fetchone())[0]
        cur = await db.execute("SELECT COUNT(*) FROM comments"); c = (await cur.fetchone())[0]
    await message.answer(f"📊 Юзеров: {u}\n📝 Постов: {p}\n💬 Комментариев: {c}")

@dp.message(Command("ban"))
async def ban_cmd(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return
    try:
        target = int(message.text.split()[1])
        async with aiosqlite.connect(DB) as db:
            await db.execute("UPDATE users SET is_banned=1 WHERE id=?", (target,))
            await db.commit()
        await message.answer("🚫 Забанен.")
    except: await message.answer("Формат: /ban <id>")

@dp.message(Command("freeze"))
async def freeze_cmd(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return
    try:
        target = int(message.text.split()[1])
        async with aiosqlite.connect(DB) as db:
            await db.execute("UPDATE users SET is_frozen=1 WHERE id=?", (target,))
            await db.commit()
        await message.answer("❄️ Пользователь заморожен.")
    except: await message.answer("Формат: /freeze <id>")

@dp.message(Command("strike"))
async def strike_cmd(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return
    try:
        args = message.text.split(maxsplit=2)
        target, reason = int(args[1]), args[2]
        async with aiosqlite.connect(DB) as db:
            await db.execute("INSERT INTO strikes(user_id, reason) VALUES (?,?)", (target, reason))
            await db.commit()
            cur = await db.execute("SELECT COUNT(*) FROM strikes WHERE user_id=?", (target,))
            cnt = (await cur.fetchone())[0]
        await message.answer(f"⚡ Страйк выдан ({cnt}/3). Причина: {reason}")
    except: await message.answer("Формат: /strike <id> <причина>")

@dp.message(Command("badge"))
async def badge_cmd(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return
    try:
        args = message.text.split(); target, b = int(args[1]), args[2]
        async with aiosqlite.connect(DB) as db:
            await db.execute("UPDATE users SET badge=? WHERE id=?", (b, target))
            await db.commit()
        await message.answer("✅ Бейдж выдан!")
    except: await message.answer("Формат: /badge <id> <текст>")

@dp.message(Command("give_crystals"))
async def give_crystals(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return
    try:
        args = message.text.split(); target, amt = int(args[1]), int(args[2])
        async with aiosqlite.connect(DB) as db:
            await db.execute("UPDATE users SET crystals = crystals + ? WHERE id=?", (amt, target))
            await db.commit()
        await message.answer(f"✅ Выдано {amt} 💎")
    except: await message.answer("Формат: /give_crystals <id> <сумма>")

@dp.message(Command("add_banner"))
async def add_banner(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return
    try:
        args = message.text.split(maxsplit=3)
        name, price, url = args[1], int(args[2]), args[3]
        async with aiosqlite.connect(DB) as db:
            await db.execute("INSERT INTO banners(name, price, image_url) VALUES (?,?,?)", (name, price, url))
            await db.commit()
        await message.answer("✅ Баннер добавлен!")
    except: await message.answer("Формат: /add_banner <название> <цена> <url>")

@dp.message(Command("remove_banner"))
async def remove_banner(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return
    try:
        bid = int(message.text.split()[1])
        async with aiosqlite.connect(DB) as db:
            await db.execute("DELETE FROM banners WHERE id=?", (bid,))
            await db.commit()
        await message.answer("✅ Баннер удалён.")
    except: await message.answer("Формат: /remove_banner <id>")

@dp.message(Command("add_promo"))
async def add_promo(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return
    try:
        args = message.text.split()
        code, amount, limit = args[1], int(args[2]), int(args[3])
        async with aiosqlite.connect(DB) as db:
            await db.execute("INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                             (f"promo_{code}", json.dumps({"amount": amount, "limit": limit, "used": 0})))
            await db.commit()
        await message.answer(f"✅ Промокод {code} на {amount} 💎 (лимит {limit}) создан.")
    except: await message.answer("Формат: /add_promo <код> <сумма> <лимит>")

@dp.message(Command("broadcast"))
async def broadcast(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return
    text = message.text.replace("/broadcast", "").strip()
    if not text: return await message.answer("Формат: /broadcast <текст>")
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("SELECT id FROM users WHERE is_banned=0")
        users = await cur.fetchall()
    sent = 0
    for (uid,) in users:
        try:
            await bot.send_message(uid, text)
            sent += 1
        except: pass
        await asyncio.sleep(0.05)
    await message.answer(f"✅ Рассылка отправлена {sent} пользователям.")

@dp.message(Command("remove_track"))
async def remove_track(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return
    try:
        idx = int(message.text.split()[1]) - 1
        async with aiosqlite.connect(DB) as db:
            cur = await db.execute("SELECT value FROM settings WHERE key='playlist'")
            row = await cur.fetchone(); pl = json.loads(row[0]) if row and row[0] else []
            if 0 <= idx < len(pl):
                pl.pop(idx)
                await db.execute("UPDATE settings SET value=? WHERE key='playlist'", (json.dumps(pl),))
                await db.commit()
                await message.answer(f"✅ Трек {idx+1} удалён. Осталось: {len(pl)}")
            else:
                await message.answer("Нет такого трека.")
    except: await message.answer("Формат: /remove_track <номер>")

@dp.message(Command("redeem"))
async def redeem_cmd(message: types.Message):
    try:
        code = message.text.split()[1]
        async with aiosqlite.connect(DB) as db:
            cur = await db.execute("SELECT value FROM settings WHERE key=?", (f"promo_{code}",))
            row = await cur.fetchone()
            if not row:
                return await message.answer("❌ Неверный промокод.")
            promo = json.loads(row[0])
            if promo["used"] >= promo["limit"]:
                return await message.answer("❌ Лимит промокода исчерпан.")
            cur = await db.execute("SELECT 1 FROM promo_uses WHERE user_id=? AND code=?", (message.from_user.id, code))
            if await cur.fetchone():
                return await message.answer("❌ Ты уже активировал этот промокод.")
            await db.execute("UPDATE users SET crystals = crystals + ? WHERE id=?", (promo["amount"], message.from_user.id))
            await db.execute("INSERT INTO promo_uses(user_id, code) VALUES (?,?)", (message.from_user.id, code))
            promo["used"] += 1
            await db.execute("UPDATE settings SET value=? WHERE key=?", (json.dumps(promo), f"promo_{code}"))
            await db.commit()
        await message.answer(f"✅ Промокод активирован! +{promo['amount']} 💎")
    except: await message.answer("Формат: /redeem <код>")

@dp.message(Command("share"))
async def share_cmd(message: types.Message):
    try:
        post_id = int(message.text.split()[1])
        async with aiosqlite.connect(DB) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT title, body, tags FROM posts WHERE id=?", (post_id,))
            post = await cur.fetchone()
        if not post:
            return await message.answer("❌ Пост не найден.")
        text = f"📖 <b>{post['title']}</b>\n\n{post['body'][:500]}\n\n🔗 <a href='{APP_URL}/#post/{post_id}'>Открыть пост</a>\n# {post['tags']}"
        await message.answer(text, parse_mode="HTML")
    except: await message.answer("Формат: /share <post_id>")

@dp.message(Command("report_user"))
async def report_user_cmd(message: types.Message):
    try:
        args = message.text.split(maxsplit=2)
        target, reason = int(args[1]), args[2]
        async with aiosqlite.connect(DB) as db:
            await db.execute("INSERT INTO reports(reporter_id, target_type, target_id, reason) VALUES (?,?,?,?)", (message.from_user.id, "user", target, reason))
            await db.commit()
        for admin in ADMIN_IDS:
            try:
                await bot.send_message(admin, f"🚩 Жалоба на пользователя {target}\nПричина: {reason}\nОт: {message.from_user.id}")
            except: pass
        await message.answer("✅ Жалоба отправлена админу.")
    except: await message.answer("Формат: /report_user <id> <причина>")

@dp.message(Command("appeal"))
async def appeal_cmd(message: types.Message):
    reason = message.text.replace("/appeal", "").strip()
    if not reason: return await message.answer("Формат: /appeal <текст>")
    for admin in ADMIN_IDS:
        try:
            await bot.send_message(admin, f"⚖️ Апелляция от {message.from_user.id}\n{reason}")
        except: pass
    await message.answer("✅ Апелляция отправлена.")

@dp.message(F.sticker | F.animation | F.photo)
async def handle_media(message: types.Message):
    fid = message.sticker.file_id if message.sticker else (message.animation.file_id if message.animation else message.photo[-1].file_id)
    await message.answer(f"📎 Твой file_id:\n<code>{fid}</code>\n\nВставь его в комментарий или пост.", parse_mode="HTML")

@dp.message(F.audio | F.document)
async def handle_music(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return
    fid = message.audio.file_id if message.audio else message.document.file_id
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("SELECT value FROM settings WHERE key='playlist'")
        row = await cur.fetchone(); pl = json.loads(row[0]) if row and row[0] else []
        pl.append(fid)
        await db.execute("UPDATE settings SET value=? WHERE key='playlist'", (json.dumps(pl),))
        await db.commit()
    await message.answer(f"🎵 Трек добавлен! Всего: {len(pl)}")

@dp.callback_query(F.data.startswith("mod_"))
async def mod_action(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return await callback.answer("Нет доступа", show_alert=True)
    action, post_id = callback.data.split("_")[1], callback.data.split("_")[2]
    async with aiosqlite.connect(DB) as db:
        if action == "ok":
            await db.execute("UPDATE posts SET status='approved' WHERE id=?", (post_id,))
            new_text = (callback.message.caption or callback.message.text or "") + "\n\n✅ <b>ОДОБРЕНО</b>"
            if callback.message.caption: await callback.message.edit_caption(caption=new_text, parse_mode="HTML")
            else: await callback.message.edit_text(text=new_text, parse_mode="HTML")
        else:
            await db.execute("DELETE FROM posts WHERE id=?", (post_id,))
            new_text = (callback.message.caption or callback.message.text or "") + "\n\n❌ <b>ОТКЛОНЕНО</b>"
            if callback.message.caption: await callback.message.edit_caption(caption=new_text, parse_mode="HTML")
            else: await callback.message.edit_text(text=new_text, parse_mode="HTML")
        await db.commit()
    await callback.answer("Готово!")

async def set_commands():
    await bot.set_my_commands([
        types.BotCommand(command="start", description="Запуск ⛩️"),
        types.BotCommand(command="support", description="Поддержка 🆘"),
        types.BotCommand(command="redeem", description="Промокод 🎁"),
        types.BotCommand(command="appeal", description="Апелляция ⚖️"),
        types.BotCommand(command="stats", description="Статистика 📊"),
        types.BotCommand(command="admin", description="Админ 🛡️")
    ])
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())

async def start_keep_alive(): asyncio.create_task(keep_alive())
