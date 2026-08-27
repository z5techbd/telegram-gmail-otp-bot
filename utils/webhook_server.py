import json
import base64
import aiohttp
from aiohttp import web
from database import get_all_gmail_accounts, update_last_delivered_otp, update_last_delivered_tempmail_otp, get_tempmail, save_gmail_account
from utils.gmail_api import fetch_fast_latest_gmail_otp, refresh_access_token
from utils.keyboards import get_otp_delivery_menu
from utils.emojis import TG_STAR

async def handle_health_check(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok", "service": "gtmail-bot-webhook"})

async def handle_gmail_webhook(request: web.Request) -> web.Response:
    """Handles real-time Google Pub/Sub Webhook Push Notifications."""
    bot = request.app.get("bot")
    print(f"[WebhookHTTP] 📥 Incoming Webhook HTTP POST request received!")
    try:
        data = await request.json()
        print(f"[WebhookHTTP] Payload: {json.dumps(data)}")
    except Exception as err:
        print(f"[WebhookHTTP] Failed to parse JSON body: {err}")
        return web.json_response({"error": "Invalid JSON"}, status=400)

    email_address = None
    # Parse Google Cloud Pub/Sub envelope
    if "message" in data and "data" in data["message"]:
        try:
            raw_payload = base64.b64decode(data["message"]["data"]).decode("utf-8")
            print(f"[WebhookHTTP] Decoded Pub/Sub data: {raw_payload}")
            payload_json = json.loads(raw_payload)
            email_address = payload_json.get("emailAddress")
        except Exception as err:
            print(f"[WebhookHTTP] Error parsing Pub/Sub payload: {err}")

    # Fallback to direct JSON webhook
    if not email_address:
        email_address = data.get("emailAddress") or data.get("email")

    all_accounts = await get_all_gmail_accounts()
    if not all_accounts:
        print(f"[WebhookHTTP] No registered Gmail accounts in database.")
        return web.json_response({"status": "ignored", "reason": "No accounts registered"})

    # Filter target accounts
    target_accounts = []
    if email_address:
        for acc in all_accounts:
            if acc["email"].lower() == email_address.lower():
                target_accounts.append(acc)
    else:
        # If Pub/Sub envelope didn't include emailAddress, check all connected accounts
        target_accounts = all_accounts

    if not target_accounts:
        print(f"[WebhookHTTP] Email '{email_address}' not found in database.")
        return web.json_response({"status": "ignored", "reason": "Email account not registered"})

    otp_delivered = False
    for target_acc in target_accounts:
        user_id = target_acc["user_id"]
        access_token = target_acc["access_token"]
        last_delivered_msg_id = target_acc.get("last_msg_id")

        conn = aiohttp.TCPConnector(limit=5, keepalive_timeout=60)
        async with aiohttp.ClientSession(connector=conn) as session:
            fast_res = await fetch_fast_latest_gmail_otp(session, access_token, known_last_msg_id=last_delivered_msg_id)
            if fast_res.get("auth_failed") and target_acc.get("refresh_token"):
                rf_res = await refresh_access_token(target_acc["refresh_token"])
                if rf_res.get("success"):
                    access_token = rf_res["access_token"]
                    await save_gmail_account(user_id, target_acc["email"], access_token, target_acc["refresh_token"], rf_res["expires_in"])
                    fast_res = await fetch_fast_latest_gmail_otp(session, access_token, known_last_msg_id=last_delivered_msg_id)

        if fast_res.get("has_new"):
            found_otp = fast_res.get("otp")
            found_msg_id = fast_res.get("id")
            if found_otp and found_msg_id and found_msg_id != last_delivered_msg_id:
                await update_last_delivered_otp(user_id, found_msg_id, found_otp)
                if bot:
                    try:
                        otp_msg_text = f"{TG_STAR} <b>New OTP Received</b>"
                        await bot.send_message(user_id, otp_msg_text, parse_mode="html", buttons=get_otp_delivery_menu(found_otp))
                        print(f"[WebhookHTTP] ⚡ INSTANT OTP Delivered via Webhook to user {user_id}: {found_otp}")
                        otp_delivered = True
                    except Exception as send_err:
                        print(f"[WebhookHTTP] Error sending Telegram message to {user_id}: {send_err}")
            return web.json_response({"status": "otp_delivered", "otp": found_otp})

    return web.json_response({"status": "processed"})

async def handle_tempmail_webhook(request: web.Request) -> web.Response:
    """Handles incoming TempMail Webhook callbacks."""
    bot = request.app.get("bot")
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    user_id = data.get("user_id")
    otp = data.get("otp")
    msg_id = data.get("id", "")

    if user_id and otp and bot:
        await update_last_delivered_tempmail_otp(user_id, msg_id, otp)
        try:
            otp_msg_text = f"{TG_STAR} <b>New OTP Received</b>"
            await bot.send_message(user_id, otp_msg_text, parse_mode="html", buttons=get_otp_delivery_menu(otp))
            print(f"[TempMailWebhook] ⚡ Instant TempMail OTP delivered to {user_id}: {otp}")
        except Exception as e:
            print(f"[TempMailWebhook] Error sending message: {e}")
        return web.json_response({"status": "delivered"})

    return web.json_response({"status": "ignored"})

def create_webhook_app(bot_instance=None) -> web.Application:
    app = web.Application()
    if bot_instance:
        app["bot"] = bot_instance
    app.router.add_get("/health", handle_health_check)
    app.router.add_post("/webhook/gmail", handle_gmail_webhook)
    app.router.add_post("/webhook/tempmail", handle_tempmail_webhook)
    return app
