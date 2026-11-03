import asyncio
import os
import uvicorn
from bot import dp, bot, set_commands, start_keep_alive
from database import init_db

async def run_bot():
    await bot.delete_webhook(drop_pending_updates=True)
    await set_commands()
    await start_keep_alive()
    await dp.start_polling(bot)

async def run_api():
    port = int(os.environ.get("PORT", 8000))
    config = uvicorn.Config("api:app", host="0.0.0.0", port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()

async def main():
    await init_db()
    await asyncio.gather(run_bot(), run_api())

if __name__ == "__main__":
    asyncio.run(main())
