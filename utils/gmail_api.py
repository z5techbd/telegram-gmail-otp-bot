import aiohttp
import urllib.parse
import re
import json
import base64
import asyncio
from config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI

GMAIL_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GMAIL_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"

def get_google_auth_url(state: str = "") -> str:
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "https://www.googleapis.com/auth/gmail.readonly",
        "access_type": "offline",
        "prompt": "select_account consent",
        "state": state
    }
    return f"{GMAIL_AUTH_URL}?{urllib.parse.urlencode(params)}"

async def exchange_code_for_tokens(code: str) -> dict:
    clean_code = code.strip()
    if "code=" in clean_code:
        m = re.search(r'[?&]code=([^&\s]+)', clean_code)
        if m:
            clean_code = urllib.parse.unquote(m.group(1))
    else:
        clean_code = urllib.parse.unquote(clean_code)

    async with aiohttp.ClientSession() as session:
        payload = {
            "code": clean_code,
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri": GOOGLE_REDIRECT_URI,
            "grant_type": "authorization_code"
        }
        async with session.post(GMAIL_TOKEN_URL, data=payload) as resp:
            data = await resp.json()
            if resp.status == 200 and "access_token" in data:
                email = ""
                if "id_token" in data:
                    try:
                        payload_part = data["id_token"].split(".")[1]
                        padded = payload_part + "=" * (-len(payload_part) % 4)
                        claims = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
                        email = claims.get("email", "")
                    except Exception:
                        pass
                return {
                    "success": True,
                    "access_token": data.get("access_token"),
                    "refresh_token": data.get("refresh_token", ""),
                    "expires_in": data.get("expires_in", 3600),
                    "email": email
                }
            return {
                "success": False,
                "error": data.get("error_description", data.get("error", "Failed to exchange authorization code"))
            }

async def refresh_access_token(refresh_token: str) -> dict:
    async with aiohttp.ClientSession() as session:
        payload = {
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token"
        }
        async with session.post(GMAIL_TOKEN_URL, data=payload) as resp:
            data = await resp.json()
            if resp.status == 200 and "access_token" in data:
                return {
                    "success": True,
                    "access_token": data.get("access_token"),
                    "expires_in": data.get("expires_in", 3600)
                }
            return {"success": False, "error": data.get("error_description", "Token refresh failed")}

async def get_user_gmail_profile(access_token: str) -> dict:
    headers = {"Authorization": f"Bearer {access_token}"}
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{GMAIL_API_BASE}/profile", headers=headers) as resp:
            if resp.status == 200:
                data = await resp.json()
                return {"success": True, "email": data.get("emailAddress")}
            return {"success": False, "error": "Profile fetch failed"}

async def setup_gmail_watch(access_token: str, topic_name: str) -> dict:
    """Subscribes Gmail mailbox to Google Cloud Pub/Sub Push Webhook notifications."""
    if not topic_name:
        return {"success": False, "error": "No Pub/Sub topic provided"}
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    payload = {
        "topicName": topic_name,
        "labelIds": ["INBOX"]
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{GMAIL_API_BASE}/watch", headers=headers, json=payload) as resp:
            if resp.status == 200:
                data = await resp.json()
                return {"success": True, "historyId": data.get("historyId"), "expiration": data.get("expiration")}
            data = await resp.json()
            return {"success": False, "error": data.get("error", {}).get("message", "Failed to setup Gmail watch")}

async def stop_gmail_watch(access_token: str) -> dict:
    headers = {"Authorization": f"Bearer {access_token}"}
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{GMAIL_API_BASE}/stop", headers=headers) as resp:
            return {"success": resp.status in (200, 204)}

def extract_telegram_5digit_otp(subject: str, snippet: str, sender: str) -> str:
    """Specifically extracts Telegram OTP code (supports both 5-digit login codes and 6-digit verification codes)."""
    # 1. Subject match: "Your Code - 785197" or "Your Code - 72694"
    sub_match = re.search(r'(?:Your Code|code)\s*[-:]\s*([0-9]{4,8})', subject, re.IGNORECASE)
    if sub_match:
        return sub_match.group(1)
        
    # 2. Body/Snippet match: "Your code is: 785197" or "Your code is: 72694"
    body_match = re.search(r'(?:Your code is|code is|code)[:\s]+([0-9]{4,8})', snippet, re.IGNORECASE)
    if body_match:
        return body_match.group(1)
        
    is_tg = "telegram" in sender.lower() or "telegram" in subject.lower() or "your code" in subject.lower()
    if is_tg:
        digit_match = re.search(r'([0-9]{5,6})', f"{subject} {snippet}")
        if digit_match:
            return digit_match.group(1)
            
    # 4. Fallback general 4-8 digit regex
    gen_match = re.search(r'(?:code|otp|verification|pin)[:\s]+([0-9]{4,8})', f"{subject} {snippet}", re.IGNORECASE)
    if gen_match:
        return gen_match.group(1)
        
    return ""

async def fetch_fast_latest_gmail_otp(session: aiohttp.ClientSession, access_token: str, known_last_msg_id: str = None) -> dict:
    """Ultra-fast zero-delay Gmail checker checking top messages in parallel."""
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        async with session.get(f"{GMAIL_API_BASE}/messages?maxResults=5&includeSpamTrash=true", headers=headers) as resp:
            if resp.status == 401:
                return {"auth_failed": True, "has_new": False}
            if resp.status != 200:
                return {"has_new": False}
            data = await resp.json()
            messages = data.get("messages", [])
            if not messages:
                return {"has_new": False}

        # If top message ID is already delivered, return immediately in 50ms
        if known_last_msg_id and messages[0]["id"] == known_last_msg_id:
            return {"has_new": False, "id": messages[0]["id"]}

        # Check top messages up to known_last_msg_id in parallel
        tasks = []
        ids = []
        for m in messages[:4]:
            mid = m["id"]
            if known_last_msg_id and mid == known_last_msg_id:
                break
            ids.append(mid)
            tasks.append(
                session.get(
                    f"{GMAIL_API_BASE}/messages/{mid}?format=metadata&metadataHeaders=Subject&metadataHeaders=From",
                    headers=headers
                )
            )

        if not tasks:
            return {"has_new": False}

        resps = await asyncio.gather(*tasks, return_exceptions=True)
        for mid, r in zip(ids, resps):
            if isinstance(r, aiohttp.ClientResponse) and r.status == 200:
                m_data = await r.json()
                headers_dict = {h.get("name").lower(): h.get("value") for h in m_data.get("payload", {}).get("headers", [])}
                subject = headers_dict.get("subject", "")
                sender = headers_dict.get("from", "")
                snippet = m_data.get("snippet", "")
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

        return {"has_new": False, "top_id": messages[0]["id"]}
    except Exception as e:
        return {"has_new": False, "error": str(e)}

async def fetch_latest_gmail_messages(access_token: str, max_results: int = 3) -> list:
    headers = {"Authorization": f"Bearer {access_token}"}
    messages_out = []
    
    async with aiohttp.ClientSession() as session:
        # Fetch raw latest messages from timeline directly
        async with session.get(f"{GMAIL_API_BASE}/messages?maxResults={max_results}&includeSpamTrash=true", headers=headers) as resp:
            if resp.status != 200:
                return []
            data = await resp.json()
            msg_list = data.get("messages", [])
                    
        for m in msg_list:
            msg_id = m.get("id")
            async with session.get(
                f"{GMAIL_API_BASE}/messages/{msg_id}?format=metadata&metadataHeaders=Subject&metadataHeaders=From",
                headers=headers
            ) as m_resp:
                if m_resp.status != 200:
                    continue
                m_data = await m_resp.json()
                headers_dict = {h.get("name").lower(): h.get("value") for h in m_data.get("payload", {}).get("headers", [])}
                subject = headers_dict.get("subject", "No Subject")
                sender = headers_dict.get("from", "Unknown")
                snippet = m_data.get("snippet", "")
                
                # Extract Telegram OTP
                otp = extract_telegram_5digit_otp(subject, snippet, sender)
                is_telegram = "telegram" in sender.lower() or "telegram" in subject.lower() or bool(otp)
                
                messages_out.append({
                    "id": msg_id,
                    "subject": subject,
                    "from": sender,
                    "snippet": snippet,
                    "otp": otp,
                    "is_telegram": is_telegram
                })
        return messages_out
