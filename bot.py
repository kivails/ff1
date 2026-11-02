import asyncio, os
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import WebAppInfo, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
import aiosqlite
from database import DB, init_db

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
APP_URL = os.environ.get("APP_URL", "https://твой-сайт.onrender.com")
ADMIN_IDS = {5024935475}

bot = Bot(BOT_TOKEN)
dp = Dispatcher()

@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    # Аниме гифка (можно заменить на свой file_id)
    GIF_URL = "https://media.giphy.com/media/VbnUQpnihPSIgIXuZv/giphy.gif"
    kb = InlineKeyboardBuilder()
    kb.button(text="📖 Открыть RaReads", web_app=WebAppInfo(url=APP_URL))
    
    await message.answer_animation(
        animation=GIF_URL,
        caption=f"Привет, <b>{message.from_user.first_name}</b>! ⛩️\n\nДобро пожаловать в <b>RaReads</b> — твой аниме-уголок для общения и постов.\n\nВыбирай кнопку ниже, чтобы начать!",
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )

@dp.message(Command("rules"))
async def rules(message: types.Message):
    await message.answer("📜 <b>Правила RaReads:</b>\n1. Без спама (КД 15 мин).\n2. Уважай других.\n3. Модерация проверяет все посты.\n\nНарушение = бан! 🚫", parse_mode="HTML")

@dp.message(Command("profile"))
async def profile_cmd(message: types.Message):
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT score FROM posts WHERE author_id=?", (message.from_user.id,))
        p = sum(r[0] for r in await cur.fetchall())
        cur = await db.execute("SELECT score FROM comments WHERE author_id=?", (message.from_user.id,))
        c = sum(r[0] for r in await cur.fetchall())
    
    text = f"👤 <b>Твой профиль в RaReads</b>\n\n🆔 ID: <code>{message.from_user.id}</code>\n⭐ Карма: {p + c}\n\n<i>Чтобы изменить ник или аватар, зайди в приложение!</i>"
    await message.answer(text, parse_mode="HTML")

@dp.message(Command("admin"))
async def admin_cmd(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return
    await message.answer("🛡️ Команды админа:\n/tag <название> <цвет> - создать светящийся тег\n\nЖалобы и модерация приходят сюда автоматически.")

@dp.message(Command("tag"))
async def create_tag(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return
    args = message.text.split()
    if len(args) < 3: return await message.answer("Формат: /tag <название> <#hex-цвет>")
    name, color = args[1], args[2]
    async with aiosqlite.connect(DB) as db:
        await db.execute("INSERT OR REPLACE INTO tags(name, color) VALUES (?, ?)", (name, color))
        await db.commit()
    await message.answer(f"✅ Тег <b>{name}</b> создан с цветом {color}!", parse_mode="HTML")

# Обработчик кнопок модерации
@dp.callback_query(F.data.startswith("mod_"))
async def mod_action(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return await callback.answer("Нет доступа", show_alert=True)
    action, post_id = callback.data.split("_")[1], callback.data.split("_")[2]
    
    async with aiosqlite.connect(DB) as db:
        if action == "ok":
            await db.execute("UPDATE posts SET status='approved' WHERE id=?", (post_id,))
            await callback.message.edit_text(callback.message.text + "\n\n✅ <b>ОДОБРЕНО</b>", parse_mode="HTML")
        else:
            await db.execute("DELETE FROM posts WHERE id=?", (post_id,))
            await callback.message.edit_text(callback.message.text + "\n\n❌ <b>ОТКЛОНЕНО И УДАЛЕНО</b>", parse_mode="HTML")
        await db.commit()
    await callback.answer("Готово!")

async def main():
    await init_db()
    await bot.set_my_commands([
        types.BotCommand(command="start", description="Запустить RaReads ⛩️"),
        types.BotCommand(command="profile", description="Мой профиль 👤"),
        types.BotCommand(command="rules", description="Правила 📜"),
        types.BotCommand(command="admin", description="Панель админа 🛡️"),
    ])
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
