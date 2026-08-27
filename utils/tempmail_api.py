import aiohttp
import random
import string
import re

MAILTM_BASE = "https://api.mail.tm"

def generate_random_name(length=10):
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=length))

async def create_tempmail_account() -> dict:
    async with aiohttp.ClientSession() as session:
        try:
            # 1. Get available domains
            async with session.get(f"{MAILTM_BASE}/domains") as resp:
                if resp.status != 200:
                    return {"success": False, "error": "Failed to fetch domains"}
                data = await resp.json()
                domains = data.get("hydra:member", [])
                if not domains:
                    return {"success": False, "error": "No domains available"}
                domain = random.choice(domains).get("domain")
                
            username = generate_random_name(10)
            email = f"{username}@{domain}"
            password = generate_random_name(12)
            
            # 2. Register account
            payload = {"address": email, "password": password}
            async with session.post(f"{MAILTM_BASE}/accounts", json=payload) as resp:
                if resp.status not in (200, 201):
                    return {"success": False, "error": "Account registration failed"}
                    
            # 3. Get JWT token
            async with session.post(f"{MAILTM_BASE}/token", json=payload) as resp:
                if resp.status == 200:
                    tok_data = await resp.json()
                    return {
                        "success": True,
                        "email": email,
                        "token": tok_data.get("token"),
                        "password": password
                    }
                return {"success": False, "error": "Token acquisition failed"}
        except Exception as e:
            return {"success": False, "error": str(e)}

from utils.gmail_api import extract_telegram_5digit_otp

async def fetch_fast_tempmail_otp(session: aiohttp.ClientSession, token: str, known_last_msg_id: str = None) -> dict:
    """Super-fast TempMail OTP checker reusing persistent session."""
    headers = {"Authorization": f"Bearer {token}"}
    try:
        async with session.get(f"{MAILTM_BASE}/messages", headers=headers) as resp:
            if resp.status == 401:
                return {"auth_failed": True, "has_new": False}
            if resp.status != 200:
                return {"has_new": False}
            data = await resp.json()
            messages = data.get("hydra:member", [])
            if not messages:
                return {"has_new": False}
                
        # If top message ID is already delivered, return immediately
        if known_last_msg_id and messages[0].get("id") == known_last_msg_id:
            return {"has_new": False, "id": messages[0].get("id")}
            
        for m in messages[:4]:
            mid = m.get("id")
            if known_last_msg_id and mid == known_last_msg_id:
                break
            subject = m.get("subject", "")
            sender = m.get("from", {}).get("address", "")
            snippet = m.get("intro", "")
            otp = extract_telegram_5digit_otp(subject, snippet, sender)
            if otp:
                return {
                    "has_new": True,
                    "id": mid,
                    "otp": otp,
                    "subject": subject,
                    "from": sender,
                    "snippet": snippet
                }
        return {"has_new": False, "top_id": messages[0].get("id")}
    except Exception as e:
        return {"has_new": False, "error": str(e)}

async def fetch_tempmail_messages(token: str) -> list:
    headers = {"Authorization": f"Bearer {token}"}
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(f"{MAILTM_BASE}/messages", headers=headers) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                messages = data.get("hydra:member", [])
                
                results = []
                for m in messages:
                    subject = m.get("subject", "")
                    sender = m.get("from", {}).get("address", "")
                    snippet = m.get("intro", "")
                    
                    # Use shared Telegram OTP extractor
                    otp = extract_telegram_5digit_otp(subject, snippet, sender)
                    
                    results.append({
                        "id": m.get("id"),
                        "subject": subject,
                        "from": sender,
                        "snippet": snippet,
                        "otp": otp,
                        "created_at": m.get("createdAt")
                    })
                return results
        except:
            return []
