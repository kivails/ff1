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
            async with httpx.AsyncClient() as client: await client.get(f"{APP_URL}/ping")
        except: pass
        await asyncio.sleep(300)

@dp.message(CommandStart())
async def start_cmd(message: types.Message):
    async with aiosqlite.connect(DB) as db:
        await db.execute("INSERT OR IGNORE INTO users(id, username, first_name) VALUES (?,?,?)", (message.from_user.id, message.from_user.username, message.from_user.first_name))
        await db.commit()
    GIF_URL = "https://media.giphy.com/media/VbnUQpnihPSIgIXuZv/giphy.gif"
    kb = InlineKeyboardBuilder(); kb.button(text="📖 Открыть RaReads", web_app=WebAppInfo(url=APP_URL))
    await message.answer_animation(animation=GIF_URL, caption=f"Привет, <b>{message.from_user.first_name}</b>! ⛩️", parse_mode="HTML", reply_markup=kb.as_markup())

@dp.message(Command("admin"))
async def admin_cmd(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return
    await message.answer("🛡️ Админ-команды:\n/stats\n/badge <id> <текст>\n/ban <id>\n/give_crystals <id> <сумма>")

@dp.message(Command("stats"))
async def stats_cmd(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("SELECT COUNT(*) FROM users"); u = (await cur.fetchone())[0]
        cur = await db.execute("SELECT COUNT(*) FROM posts"); p = (await cur.fetchone())[0]
    await message.answer(f"📊 Юзеров: {u}\n📝 Постов: {p}")

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

@dp.message(Command("roulette"))
async def roulette_cmd(message: types.Message):
    async with aiosqlite.connect(DB) as db:
        await db.execute("INSERT OR IGNORE INTO users(id, username, first_name) VALUES (?,?,?)", (message.from_user.id, message.from_user.username, message.from_user.first_name))
        cur = await db.execute("SELECT last_roulette FROM users WHERE id=?", (message.from_user.id,))
        last = await cur.fetchone()
        now = datetime.datetime.utcnow()
        if last and last[0] and (now - datetime.datetime.fromisoformat(last[0])).total_seconds() < 43200:
            return await message.answer("⏳ Рулетка доступна раз в 12 часов!")
        win = random.choice([0, 1, 2, 5, 10])
        await db.execute("UPDATE users SET crystals = crystals + ?, last_roulette=? WHERE id=?", (win, now.isoformat(), message.from_user.id))
        await db.commit()
    await message.answer(f"🎰 Ты выиграл {win} 💎!")

@dp.message(Command("slots"))
async def slots_cmd(message: types.Message):
    icons = ["🍒", "🍋", "💎", "7️⃣", "⭐"]
    res = [random.choice(icons) for _ in range(3)]
    win = 0
    if res[0] == res[1] == res[2]: win = 50 if res[0] == "💎" else 20
    elif res[0] == res[1] or res[1] == res[2]: win = 5
    async with aiosqlite.connect(DB) as db:
        await db.execute("INSERT OR IGNORE INTO users(id, username, first_name) VALUES (?,?,?)", (message.from_user.id, message.from_user.username, message.from_user.first_name))
        await db.execute("UPDATE users SET crystals = crystals + ? WHERE id=?", (win, message.from_user.id))
        await db.commit()
    await message.answer(f"🎰 {' | '.join(res)}\n\nВыигрыш: {win} 💎!")

@dp.message(F.sticker | F.animation | F.photo)
async def handle_media(message: types.Message):
    fid = message.sticker.file_id if message.sticker else (message.animation.file_id if message.animation else message.photo[-1].file_id)
    await message.answer(f"📎 Твой file_id:\n<code>{fid}</code>\n\nОтправь его в комментарии (через поле 'Текст').", parse_mode="HTML")

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
        types.BotCommand(command="roulette", description="Рулетка 🎰"),
        types.BotCommand(command="slots", description="Слоты 🎰"),
        types.BotCommand(command="stats", description="Статистика 📊"),
        types.BotCommand(command="admin", description="Админ 🛡️")
    ])
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())

async def start_keep_alive(): asyncio.create_task(keep_alive())
