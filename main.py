import asyncio, os, uvicorn
from bot import dp, bot, set_commands
from database import init_db

async def main():
    await init_db()
    await set_commands()
    
    # Запуск API
    config = uvicorn.Config("api:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), log_level="info")
    server = uvicorn.Server(config)
    
    # Запуск Бота и API одновременно
    await asyncio.gather(dp.start_polling(bot), server.serve())

if __name__ == "__main__":
    asyncio.run(main())
