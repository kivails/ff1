import asyncio
import json
import aiosqlite
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import WebAppInfo, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from database import DB, init_db

BOT_TOKEN = "ТВОЙ_ТОКЕН"
APP_URL = "https://твой-домен.com"
ADMIN_IDS = {123456789}

bot = Bot(BOT_TOKEN)
dp = Dispatcher()

@dp.message(F.text == "/start")
async def start(message: types.Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="🚀 Открыть форум", web_app=WebAppInfo(url=APP_URL))
    await message.answer(
        "Добро пожаловать!\n\n"
        "• Публикуй посты и комментируй\n"
        "• Получай карму за активность\n"
        "• Отвечай на комментарии\n\n"
        "Жми кнопку чтобы начать 👇",
        reply_markup=kb.as_markup()
    )

@dp.message(F.text == "/stats")
async def stats(message: types.Message):
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("SELECT COUNT(*) FROM users")
        users = (await cur.fetchone())[0]
        cur = await db.execute("SELECT COUNT(*) FROM posts WHERE is_hidden=0")
        posts = (await cur.fetchone())[0]
        cur = await db.execute("SELECT COUNT(*) FROM comments WHERE is_hidden=0")
        comments = (await cur.fetchone())[0]
    await message.answer(
        f"📊 Статистика:\n"
        f"👥 Пользователи: {users}\n"
        f"📝 Посты: {posts}\n"
        f"💬 Комментарии: {comments}"
    )

@dp.message(F.text == "/me")
async def me(message: types.Message):
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT karma FROM users WHERE id=?", (message.from_user.id,))
        row = await cur.fetchone()
    karma = row["karma"] if row else 0
    await message.answer(f"⭐ Твоя карма: {karma}")

@dp.message(F.text == "/admin")
async def admin(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return await message.answer("Нет доступа")
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("SELECT COUNT(*) FROM reports WHERE resolved=0")
        reports = (await cur.fetchone())[0]
    kb = InlineKeyboardBuilder()
    kb.button(text="🚨 Жалобы", web_app=WebAppInfo(url=APP_URL + "#admin"))
    await message.answer(f"Открытых жалоб: {reports}", reply_markup=kb.as_markup())

# Периодическая рассылка уведомлений
async def notification_worker():
    sent_ids = set()
    while True:
        try:
            async with aiosqlite.connect(DB) as db:
                db.row_factory = aiosqlite.Row
                cur = await db.execute(
                    "SELECT * FROM notifications WHERE is_read=0 ORDER BY id LIMIT 50")
                rows = await cur.fetchall()
                for n in rows:
                    if n["id"] in sent_ids: continue
                    payload = json.loads(n["payload"])
                    text = ""
                    if n["type"] == "reply":
                        text = (f"💬 {payload.get('from','Кто-то')} ответил:\n"
                                f"«{payload.get('preview','')}...»\n\n"
                                f"Открыть: {APP_URL}")
                    if text:
                        kb = InlineKeyboardBuilder()
                        kb.button(text="Открыть", web_app=WebAppInfo(url=APP_URL))
                        try:
                            await bot.send_message(n["user_id"], text,
                                                   reply_markup=kb.as_markup())
                        except Exception:
                            pass
                    sent_ids.add(n["id"])
            await asyncio.sleep(15)
        except Exception as e:
            print("worker error:", e)
            await asyncio.sleep(30)

async def main():
    await init_db()
    asyncio.create_task(notification_worker())
    await dp.start_polling(bot)

asyncio.run(main())
