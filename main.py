import asyncio
import os
import uvicorn
from aiogram import Bot, Dispatcher
from bot import dp, bot, set_commands
from database import init_db

async def run_bot():
    # Удаляем вебхук, если он был (частая причина конфликта)
    await bot.delete_webhook(drop_pending_updates=True)
    await set_commands()
    # Запускаем бота
    await dp.start_polling(bot)

async def run_api():
    # Render передает порт через переменную PORT
    port = int(os.environ.get("PORT", 8000))
    config = uvicorn.Config("api:app", host="0.0.0.0", port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()

async def main():
    await init_db()
    # Запускаем бота и сервер одновременно
    await asyncio.gather(run_bot(), run_api())

if __name__ == "__main__":
    asyncio.run(main())
