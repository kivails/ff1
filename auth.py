import os
from fastapi import HTTPException, Header
from aiogram.utils.web_app import check_webapp_signature, parse_webapp_init_data
from database import get_db

# Берем токен из переменных окружения Render
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

def verify_init_data(init_data: str) -> dict:
    """Проверяет подпись initData, используя встроенные функции aiogram."""
    if not BOT_TOKEN:
        # Если токен не задан в Render, выдаем ошибку сервера
        raise HTTPException(500, "BOT_TOKEN не настроен на сервере")
        
    if not init_data:
        raise HTTPException(401, "Отсутствуют данные авторизации (initData)")

    # check_webapp_signature делает всю сложную математику за нас
    if not check_webapp_signature(BOT_TOKEN, init_data):
        raise HTTPException(401, "Неверная подпись (bad signature)")
        
    # Парсим данные, получаем объект пользователя
    data = parse_webapp_init_data(init_data)
    return data.user

async def current_user(x_init_data: str = Header(...)) -> dict:
    """
    Зависимость для FastAPI. 
    Вызывается автоматически при каждом запросе, требует заголовок X-Init-Data.
    """
    tg_user = verify_init_data(x_init_data)
    
    # Подключаемся к базе данных
    async with await get_db() as db:
        # Добавляем пользователя в БД, если его там еще нет
        await db.execute(
            """INSERT OR IGNORE INTO users(id, username, first_name) VALUES (?,?,?)""",
            (tg_user["id"], tg_user.get("username"), tg_user.get("first_name"))
        )
        await db.commit()
        
        # Достаем полную информацию о пользователе (включая карму и бан)
        cur = await db.execute("SELECT * FROM users WHERE id=?", (tg_user["id"],))
        row = await cur.fetchone()
        
    # Если пользователь забанен, не пускаем его
    if row["is_banned"]:
        raise HTTPException(403, f"Пользователь забанен. Причина: {row['ban_reason'] or 'не указана'}")
        
    return dict(row)
