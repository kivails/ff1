import os, asyncio, httpx, random
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
        except: pass
        await asyncio.sleep(300)

@dp.message(CommandStart())
async def start_cmd(message: types.Message):
    async with aiosqlite.connect(DB) as db:
        await db.execute("INSERT OR IGNORE INTO users(id, username, first_name) VALUES (?,?,?)", (message.from_user.id, message.from_user.username, message.from_user.first_name))
        await db.commit()

    GIF_URL = "https://media.giphy.com/media/VbnUQpnihPSIgIXuZv/giphy.gif"
    kb = InlineKeyboardBuilder()
    kb.button(text="📖 Открыть RaReads", web_app=WebAppInfo(url=APP_URL))
    await message.answer_animation(animation=GIF_URL, caption=f"Привет, <b>{message.from_user.first_name}</b>! ⛩️\n\nДобро пожаловать в RaReads!", parse_mode="HTML", reply_markup=kb.as_markup())

@dp.message(Command("stats"))
async def stats_cmd(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("SELECT COUNT(*) FROM users")
        u = (await cur.fetchone())[0]
        cur = await db.execute("SELECT COUNT(*) FROM posts")
        p = (await cur.fetchone())[0]
    await message.answer(f"📊 Юзеров: {u}\n📝 Постов: {p}")

@dp.message(Command("badge"))
async def badge_cmd(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return
    try:
        args = message.text.split()
        target_id, badge = int(args[1]), args[2]
        async with aiosqlite.connect(DB) as db:
            await db.execute("UPDATE users SET badge = ? WHERE id=?", (badge, target_id))
            await db.commit()
        await message.answer(f"✅ Значок выдан.")
    except: await message.answer("Формат: /badge <id> <текст>")

@dp.message(Command("roulette"))
async def roulette_cmd(message: types.Message):
    win = random.choice([0, 1, 2, 5, 10])
    async with aiosqlite.connect(DB) as db:
        await db.execute("INSERT OR IGNORE INTO users(id, username, first_name) VALUES (?,?,?)", (message.from_user.id, message.from_user.username, message.from_user.first_name))
        await db.execute("UPDATE users SET crystals = crystals + ? WHERE id=?", (win, message.from_user.id))
        await db.commit()
    await message.answer(f"🎰 Ты выиграл {win} 💎!")

@dp.message(F.audio | F.document) 
async def handle_music(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return
    file_id = message.audio.file_id if message.audio else message.document.file_id
    async with aiosqlite.connect(DB) as db:
        await db.execute("UPDATE settings SET value=? WHERE key='music_url'", (file_id,))
        await db.commit()
    await message.answer("🎵 Музыка обновлена!")

@dp.callback_query(F.data.startswith("mod_"))
async def mod_action(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return await callback.answer("Нет доступа", show_alert=True)
    action, post_id = callback.data.split("_")[1], callback.data.split("_")[2]
    async with aiosqlite.connect(DB) as db:
        if action == "ok":
            await db.execute("UPDATE posts SET status='approved' WHERE id=?", (post_id,))
            await callback.message.edit_caption(caption=callback.message.caption + "\n\n✅ <b>ОДОБРЕНО</b>", parse_mode="HTML")
        else:
            await db.execute("DELETE FROM posts WHERE id=?", (post_id,))
            await callback.message.edit_caption(caption=callback.message.caption + "\n\n❌ <b>ОТКЛОНЕНО</b>", parse_mode="HTML")
        await db.commit()
    await callback.answer("Готово!")

async def set_commands():
    await bot.set_my_commands([
        types.BotCommand(command="start", description="Запустить ⛩️"),
        types.BotCommand(command="roulette", description="Рулетка 🎰"),
        types.BotCommand(command="stats", description="Статистика 📊"),
        types.BotCommand(command="admin", description="Админ 🛡️"),
    ])
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())

async def start_keep_alive():
    asyncio.create_task(keep_alive())
