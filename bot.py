import os
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import WebAppInfo, MenuButtonCommands, InlineKeyboardMarkup, InlineKeyboardButton
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
    GIF_URL = "https://media.giphy.com/media/VbnUQpnihPSIgIXuZv/giphy.gif"
    kb = InlineKeyboardBuilder()
    kb.button(text="📖 Открыть RaReads", web_app=WebAppInfo(url=APP_URL))
    await message.answer_animation(animation=GIF_URL, caption=f"Привет, <b>{message.from_user.first_name}</b>! ⛩️\n\nДобро пожаловать в RaReads!", parse_mode="HTML", reply_markup=kb.as_markup())

@dp.message(Command("admin"))
async def admin_cmd(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return await message.answer("Нет доступа")
    await message.answer("🛡️ Админ-панель:\n/tag <название> <цвет>")

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
        types.BotCommand(command="start", description="Запустить RaReads ⛩️"),
        types.BotCommand(command="admin", description="Панель админа 🛡️"),
    ])
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
