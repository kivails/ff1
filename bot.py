import asyncio, os
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import WebAppInfo, InlineKeyboardMarkup, InlineKeyboardButton, MenuButtonCommands
from aiogram.utils.keyboard import InlineKeyboardBuilder
import aiosqlite
from database import DB, init_db

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
APP_URL = os.environ.get("APP_URL", "https://твой-сайт.onrender.com")
ADMIN_IDS = {5024935475}

bot = Bot(BOT_TOKEN)
dp = Dispatcher()

@dp.message(CommandStart())
async def start_cmd(message: types.Message):
    args = message.text.split()
    ref_id = None
    if len(args) > 1 and args[1].startswith("ref_"):
        ref_id = int(args[1].replace("ref_", ""))
        
    async with aiosqlite.connect(DB) as db:
        await db.execute("INSERT OR IGNORE INTO users(id, username, first_name) VALUES (?,?,?)", (message.from_user.id, message.from_user.username, message.from_user.first_name))
        if ref_id:
            await db.execute("UPDATE users SET referred_by=? WHERE id=? AND referred_by IS NULL", (ref_id, message.from_user.id))
        await db.commit()

    GIF_URL = "https://media.giphy.com/media/VbnUQpnihPSIgIXuZv/giphy.gif"
    kb = InlineKeyboardBuilder()
    kb.button(text="📖 Открыть RaReads", web_app=WebAppInfo(url=APP_URL))
    
    ref_link = f"https://t.me/{(await bot.get_me()).username}?start=ref_{message.from_user.id}"
    text = (f"Привет, <b>{message.from_user.first_name}</b>! ⛩️\n\n"
            f"Добро пожаловать в <b>RaReads</b> — твой аниме-уголок.\n\n"
            f"🔗 Твоя реферальная ссылка:\n<code>{ref_link}</code>\n"
            f"Приглашай друзей и получай бонусы!")
    
    await message.answer_animation(animation=GIF_URL, caption=text, parse_mode="HTML", reply_markup=kb.as_markup())

@dp.message(Command("rules"))
async def rules(message: types.Message):
    await message.answer("📜 <b>Правила RaReads:</b>\n1. Без спама (КД 15 мин на посты, 30 мин на комменты).\n2. Уважай других.\n3. Модерация проверяет все посты.\n\nНарушение = бан! 🚫", parse_mode="HTML")

@dp.message(Command("profile"))
async def profile_cmd(message: types.Message):
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT score FROM posts WHERE author_id=?", (message.from_user.id,))
        p = sum(r[0] for r in await cur.fetchall())
        cur = await db.execute("SELECT score FROM comments WHERE author_id=?", (message.from_user.id,))
        c = sum(r[0] for r in await cur.fetchall())
        total = p + c
    
    text = f"👤 <b>Твой профиль</b>\n\n🆔 ID: <code>{message.from_user.id}</code>\n⭐ Карма: {total}\n🏆 Уровень: {total // 10}\n\n<i>Ник и био меняй в приложении!</i>"
    await message.answer(text, parse_mode="HTML")

@dp.message(Command("ref"))
async def ref_cmd(message: types.Message):
    ref_link = f"https://t.me/{(await bot.get_me()).username}?start=ref_{message.from_user.id}"
    await message.answer(f"🔗 Твоя реферальная ссылка:\n<code>{ref_link}</code>", parse_mode="HTML")

@dp.message(Command("admin"))
async def admin_cmd(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return
    await message.answer("🛡️ Команды админа:\n/tag <название> <цвет> - создать тег\n\nМодерация приходит автоматически.")

@dp.message(Command("tag"))
async def create_tag(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return
    args = message.text.split()
    if len(args) < 3: return await message.answer("Формат: /tag <название> <#hex>")
    name, color = args[1], args[2]
    async with aiosqlite.connect(DB) as db:
        await db.execute("INSERT OR REPLACE INTO tags(name, color) VALUES (?, ?)", (name, color))
        await db.commit()
    await message.answer(f"✅ Тег <b>{name}</b> создан с цветом {color}!", parse_mode="HTML")

@dp.callback_query(F.data.startswith("mod_"))
async def mod_action(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return await callback.answer("Нет доступа", show_alert=True)
    parts = callback.data.split("_")
    action, post_id = parts[1], parts[2]
    
    async with aiosqlite.connect(DB) as db:
        if action == "ok":
            await db.execute("UPDATE posts SET status='approved' WHERE id=?", (post_id,))
            await callback.message.edit_text(callback.message.text + "\n\n✅ <b>ОДОБРЕНО</b>", parse_mode="HTML")
        else:
            await db.execute("DELETE FROM posts WHERE id=?", (post_id,))
            await callback.message.edit_text(callback.message.text + "\n\n❌ <b>ОТКЛОНЕНО</b>", parse_mode="HTML")
        await db.commit()
    await callback.answer("Готово!")

async def main():
    await init_db()
    await bot.set_my_commands([
        types.BotCommand(command="start", description="Запустить RaReads ⛩️"),
        types.BotCommand(command="profile", description="Мой профиль 👤"),
        types.BotCommand(command="ref", description="Реферальная ссылка 🔗"),
        types.BotCommand(command="rules", description="Правила 📜"),
        types.BotCommand(command="admin", description="Панель админа 🛡️"),
    ])
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
