import os
from fastapi import HTTPException, Header
from aiogram.utils.web_app import check_webapp_signature, parse_webapp_init_data
from database import get_db

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

def verify_init_data(init_data: str) -> dict:
    if not BOT_TOKEN:
        raise HTTPException(500, "BOT_TOKEN не настроен на сервере")
    if not init_data:
        raise HTTPException(401, "Отсутствуют данные авторизации (initData)")
    if not check_webapp_signature(BOT_TOKEN, init_data):
        raise HTTPException(401, "Неверная подпись (bad signature)")
    return parse_webapp_init_data(init_data).user

async def current_user(x_init_data: str = Header(...)) -> dict:
    tg_user = verify_init_data(x_init_data)
    
    # ИСПРАВЛЕНИЕ: убрали await перед get_db()
    async with get_db() as db:
        await db.execute(
            """INSERT OR IGNORE INTO users(id, username, first_name) VALUES (?,?,?)""",
            (tg_user["id"], tg_user.get("username"), tg_user.get("first_name"))
        )
        await db.commit()
        
        cur = await db.execute("SELECT * FROM users WHERE id=?", (tg_user["id"],))
        row = await cur.fetchone()
        
    if row["is_banned"]:
        raise HTTPException(403, f"Пользователь забанен. Причина: {row['ban_reason'] or 'не указана'}")
        
    return dict(row)
