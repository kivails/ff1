from aiogram.utils.web_app import check_webapp_signature, parse_webapp_init_data
from fastapi import HTTPException, Header
import os

# Берем токен из настроек Render (переменная окружения)
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

def verify_init_data(init_data: str) -> dict:
    # Если токена нет - выдаем ошибку
    if not BOT_TOKEN:
        raise HTTPException(500, "BOT_TOKEN не настроен на сервере")
        
    # Проверяем подпись через встроенную функцию aiogram
    if not check_webapp_signature(BOT_TOKEN, init_data):
        raise HTTPException(401, "Ошибка подписи (неверный токен)")
        
    # Расшифровываем данные пользователя
    data = parse_webapp_init_data(init_data)
    return data.user

async def current_user(x_init_data: str = Header(...)) -> dict:
    tg_user = verify_init_data(x_init_data)
    async with await get_db() as db:
        await db.execute(
            """INSERT OR IGNORE INTO users(id, username, first_name) VALUES (?,?,?)""",
            (tg_user["id"], tg_user.get("username"), tg_user.get("first_name"))
        )
        await db.commit()
        cur = await db.execute("SELECT * FROM users WHERE id=?", (tg_user["id"],))
        row = await cur.fetchone()
    if row["is_banned"]:
        raise HTTPException(403, f"banned: {row['ban_reason'] or 'no reason'}")
    return dict(row)
