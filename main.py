import asyncio
import uvicorn
from bot import dp, bot, set_commands
from database import init_db

async def run_bot():
    await set_commands()
    await dp.start_polling(bot)

async def run_api():
    config = uvicorn.Config("api:app", host="0.0.0.0", port=8000, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()

async def main():
    await init_db()
    await asyncio.gather(run_bot(), run_api())

if __name__ == "__main__":
    asyncio.run(main())
