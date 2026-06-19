import os
import secrets
from fastapi import Header, HTTPException
from database import get_connection

# Owner token stored in .env (or fallback)
OWNER_TOKEN = os.getenv('OWNER_TOKEN', 'owner-secret-token')

def verify_owner(token: str = Header(None, alias='Authorization')):
    # Expect "Bearer <token>"
    if not token or not token.startswith('Bearer '):
        raise HTTPException(status_code=401, detail='Missing or malformed Authorization header')
    _, provided = token.split(' ', 1)
    if provided != OWNER_TOKEN:
        raise HTTPException(status_code=403, detail='Invalid owner token')
    return True

def verify_participant(token: str = Header(None, alias='Authorization')):
    if not token or not token.startswith('Bearer '):
        raise HTTPException(status_code=401, detail='Missing or malformed Authorization header')
    _, provided = token.split(' ', 1)
    conn = get_connection()
    cur = conn.cursor()
    cur.execute('SELECT participant_id, business_id FROM participants WHERE token = ?', (provided,))
    row = cur.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=403, detail='Invalid participant token')
    return {'participant_id': row['participant_id'], 'business_id': row['business_id']}

def generate_participant_token():
    return secrets.token_urlsafe(32)
