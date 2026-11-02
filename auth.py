import hmac, hashlib, json
from urllib.parse import parse_qsl
from fastapi import HTTPException, Header
from database import get_db

BOT_TOKEN = "ТВОЙ_ТОКЕН"

def verify_init_data(init_data: str) -> dict:
    parsed = dict(parse_qsl(init_data))
    received_hash = parsed.pop("hash", None)
    if not received_hash:
        raise HTTPException(401, "no hash")
    check_str = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, check_str.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, received_hash):
        raise HTTPException(401, "bad signature")
    return json.loads(parsed["user"])

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
