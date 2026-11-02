import os, random
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

@dp.message(CommandStart())
async def start_cmd(message: types.Message):
    args = message.text.split()
    if len(args) > 1 and args[1].startswith("profile_"):
        target_id = args[1].replace("profile_", "")
        await message.answer(f"👤 Профиль пользователя: {APP_URL}/#profile/{target_id}")
        return

    GIF_URL = "https://media.giphy.com/media/3o7TKu8gT2t2L8b0nS/giphy.gif"
    kb = InlineKeyboardBuilder()
    kb.button(text="📖 Открыть RaReads", web_app=WebAppInfo(url=APP_URL))
    await message.answer_animation(animation=GIF_URL, caption=f"Привет, <b>{message.from_user.first_name}</b>! ⛩️\n\nДобро пожаловать в RaReads!", parse_mode="HTML", reply_markup=kb.as_markup())

@dp.message(Command("me"))
async def me_cmd(message: types.Message):
    link = f"https://t.me/{(await bot.get_me()).username}?start=profile_{message.from_user.id}"
    await message.answer(f"👤 Твой профиль:\n<code>{link}</code>", parse_mode="HTML")

@dp.message(Command("daily"))
async def daily_cmd(message: types.Message):
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("SELECT last_daily FROM users WHERE id=?", (message.from_user.id,))
        last = await cur.fetchone()
        now = datetime.datetime.utcnow()
        if last and last[0] and (now - datetime.datetime.fromisoformat(last[0])).total_seconds() < 86400:
            return await message.answer("⏳ Возвращайся завтра!")
        await db.execute("UPDATE users SET crystals = crystals + 5, last_daily = ? WHERE id=?", (now.isoformat(), message.from_user.id))
        await db.commit()
    await message.answer("🎁 Ежедневная награда: +5 💎!")

@dp.message(Command("shop"))
async def shop_cmd(message: types.Message):
    await message.answer("🛍️ <b>Магазин:</b>\n💖 Сердечко - 10 💎\n⭐ Звезда - 30 💎\n👑 Корона - 100 💎\n\nКупить можно в приложении в профиле!")

@dp.message(Command("top"))
async def top_cmd(message: types.Message):
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("SELECT first_name, score FROM users u JOIN posts p ON u.id=p.author_id GROUP BY u.id ORDER BY SUM(p.score) DESC LIMIT 5")
        rows = await cur.fetchall()
    text = "🏆 <b>Топ-5 авторов:</b>\n\n" + "\n".join([f"{i+1}. {r[0]} — {r[1]} очков" for i, r in enumerate(rows)])
    await message.answer(text, parse_mode="HTML")

@dp.message(Command("admin"))
async def admin_cmd(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return await message.answer("Нет доступа")
    await message.answer("🛡️ Админ-команды:\n/ban <id> - забанить\n/give_crystals <id> <кол-во>\n/badge <id> <эмодзи>\n/tag <название> <цвет>")

@dp.message(Command("ban"))
async def ban_cmd(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return
    try:
        target_id = int(message.text.split()[1])
        async with aiosqlite.connect(DB) as db:
            await db.execute("UPDATE users SET is_banned=1 WHERE id=?", (target_id,))
            await db.commit()
        await message.answer(f"🚫 Пользователь {target_id} забанен.")
    except: await message.answer("Формат: /ban <id>")

@dp.message(Command("give_crystals"))
async def give_crystals(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return
    try:
        args = message.text.split()
        target_id, amount = int(args[1]), int(args[2])
        async with aiosqlite.connect(DB) as db:
            await db.execute("UPDATE users SET crystals = crystals + ? WHERE id=?", (amount, target_id))
            await db.commit()
        await message.answer(f"✅ Выдано {amount} 💎 пользователю {target_id}")
    except: await message.answer("Формат: /give_crystals <id> <кол-во>")

@dp.message(Command("badge"))
async def badge_cmd(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return
    try:
        args = message.text.split()
        target_id, badge = int(args[1]), args[2]
        async with aiosqlite.connect(DB) as db:
            await db.execute("UPDATE users SET badge = ? WHERE id=?", (badge, target_id))
            await db.commit()
        await message.answer(f"✅ Значок {badge} выдан {target_id}")
    except: await message.answer("Формат: /badge <id> <эмодзи>")

@dp.message(Command("tag"))
async def create_tag(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return
    args = message.text.split()
    if len(args) < 3: return await message.answer("Формат: /tag <название> <#hex>")
    async with aiosqlite.connect(DB) as db:
        await db.execute("INSERT OR REPLACE INTO tags(name, color) VALUES (?, ?)", (args[1], args[2]))
        await db.commit()
    await message.answer(f"✅ Тег создан!")

@dp.callback_query(F.data.startswith("mod_"))
async def mod_action(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return await callback.answer("Нет доступа", show_alert=True)
    action, post_id = callback.data.split("_")[1], callback.data.split("_")[2]
    async with aiosqlite.connect(DB) as db:
        if action == "ok":
            await db.execute("UPDATE posts SET status='approved' WHERE id=?", (post_id,))
            await callback.message.edit_caption(caption=callback.message.caption + "\n\n✅ <b>ОДОБРЕНО</b>", parse_mode="HTML") if callback.message.caption else await callback.message.edit_text(callback.message.text + "\n\n✅ <b>ОДОБРЕНО</b>", parse_mode="HTML")
        else:
            await db.execute("DELETE FROM posts WHERE id=?", (post_id,))
            await callback.message.edit_caption(caption=callback.message.caption + "\n\n❌ <b>ОТКЛОНЕНО</b>", parse_mode="HTML") if callback.message.caption else await callback.message.edit_text(callback.message.text + "\n\n❌ <b>ОТКЛОНЕНО</b>", parse_mode="HTML")
        await db.commit()
    await callback.answer("Готово!")

async def set_commands():
    await bot.set_my_commands([
        types.BotCommand(command="start", description="Запустить ⛩️"),
        types.BotCommand(command="me", description="Моя ссылка 🔗"),
        types.BotCommand(command="daily", description="Награда 🎁"),
        types.BotCommand(command="shop", description="Магазин 🛍️"),
        types.BotCommand(command="top", description="Топ 🏆"),
        types.BotCommand(command="admin", description="Админ 🛡️"),
    ])
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
