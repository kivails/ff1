import os, random, asyncio, httpx
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import WebAppInfo, MenuButtonCommands, FSInputFile
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
    GIF_URL = "https://media.tenor.com/7X5y8y7X5y8AAAAC/anime-girl.gif"
    kb = InlineKeyboardBuilder()
    kb.button(text="📖 Открыть RaReads", web_app=WebAppInfo(url=APP_URL))
    await message.answer_animation(animation=GIF_URL, caption=f"Привет, <b>{message.from_user.first_name}</b>! ⛩️\n\nДобро пожаловать в RaReads!", parse_mode="HTML", reply_markup=kb.as_markup())

@dp.message(Command("backup"))
async def backup_cmd(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return
    if os.path.exists(DB):
        await message.answer_document(FSInputFile(DB), caption="📁 Бэкап базы данных")
    else:
        await message.answer("Файл базы данных не найден.")

@dp.message(Command("restore"))
async def restore_cmd(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return
    if not message.reply_to_message or not message.reply_to_message.document:
        return await message.answer("Ответь на файл с базой данных командой /restore")
    file_id = message.reply_to_message.document.file_id
    file = await bot.get_file(file_id)
    await bot.download_file(file.file_path, DB)
    await message.answer("✅ База данных восстановлена! (Перезапусти сервис)")

@dp.message(F.audio | F.document) 
async def handle_music(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return
    file_id = message.audio.file_id if message.audio else message.document.file_id
    async with aiosqlite.connect(DB) as db:
        await db.execute("UPDATE settings SET value=? WHERE key='bg_music_1'", (file_id,))
        await db.commit()
    await message.answer("🎵 Музыка обновлена!")

@dp.message(Command("admin"))
async def admin_cmd(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return
    await message.answer("🛡️ Админ-команды:\n/ban <id>\n/give_crystals <id> <кол-во>\n/badge <id> <эмодзи>\n/tag <название> <#цвет>\n/backup - сохранить БД\n\nОтправь аудио, чтобы сменить музыку.")

@dp.message(Command("ban"))
async def ban_cmd(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return
    target_id = int(message.text.split()[1])
    async with aiosqlite.connect(DB) as db:
        await db.execute("UPDATE users SET is_banned=1 WHERE id=?", (target_id,))
        await db.commit()
    await message.answer(f"🚫 Забанен.")

@dp.message(Command("give_crystals"))
async def give_crystals(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return
    args = message.text.split()
    target_id, amount = int(args[1]), int(args[2])
    async with aiosqlite.connect(DB) as db:
        await db.execute("UPDATE users SET crystals = crystals + ? WHERE id=?", (amount, target_id))
        await db.commit()
    await message.answer(f"✅ Выдано {amount} 💎")

@dp.message(Command("badge"))
async def badge_cmd(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return
    args = message.text.split()
    target_id, badge = int(args[1]), args[2]
    async with aiosqlite.connect(DB) as db:
        await db.execute("UPDATE users SET badge = ? WHERE id=?", (badge, target_id))
        await db.commit()
    await message.answer(f"✅ Значок выдан.")

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
        types.BotCommand(command="backup", description="Бэкап БД 📁"),
        types.BotCommand(command="admin", description="Админ 🛡️"),
    ])
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())

async def start_keep_alive():
    asyncio.create_task(keep_alive())
