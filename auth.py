import os
from fastapi import HTTPException, Header
from aiogram.utils.web_app import check_webapp_signature, parse_webapp_init_data

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

def verify_init_data(init_data: str) -> dict:
    if not BOT_TOKEN: 
        raise HTTPException(500, "BOT_TOKEN не настроен")
    if not init_data: 
        raise HTTPException(401, "Нет данных")
    if not check_webapp_signature(BOT_TOKEN, init_data): 
        raise HTTPException(401, "Неверная подпись")
    
    data = parse_webapp_init_data(init_data)
    return dict(data.user)

async def current_user(x_init_data: str = Header(...)) -> dict:
    return verify_init_data(x_init_data)
