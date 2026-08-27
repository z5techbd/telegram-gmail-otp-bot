import asyncio
import aiohttp
from aiohttp import web
import io
import urllib.parse
from telethon import TelegramClient, events
from telethon.tl.types import (
    ReplyInlineMarkup,
    KeyboardButtonRow as InlineRow,
    KeyboardButtonCopy,
    KeyboardButtonCallback
)

from config import (
    API_ID,
    API_HASH,
    BOT_TOKEN,
    DEV_USERNAME,
    CHANNEL_URL,
    WEBHOOK_HOST,
    WEBHOOK_PORT,
    GOOGLE_PUBSUB_TOPIC
)
from database import (
    init_db,
    get_user_state,
    set_user_state,
    save_gmail_account,
    get_gmail_account,
    get_all_gmail_accounts,
    update_last_delivered_otp,
    delete_gmail_account,
    save_tempmail,
    get_tempmail,
    update_last_delivered_tempmail_otp,
    delete_tempmail
)
from utils.keyboards import (
    get_main_persistent_menu,
    get_start_inline_menu,
    get_gmail_inline_menu,
    get_gmail_copy_variants_menu,
    get_gmail_expired_menu,
    get_tempmail_inline_menu,
    get_tempmail_expired_menu,
    get_otp_delivery_menu,
    get_format_export_menu,
    get_dev_menu
)
from utils.variant_gen import generate_gmail_variants
from utils.gmail_api import (
    get_google_auth_url,
    exchange_code_for_tokens,
    refresh_access_token,
    get_user_gmail_profile,
    fetch_fast_latest_gmail_otp,
    fetch_latest_gmail_messages,
    setup_gmail_watch
)
from utils.tempmail_api import (
    create_tempmail_account,
    fetch_fast_tempmail_otp,
    fetch_tempmail_messages
)
from utils.webhook_server import create_webhook_app

bot = TelegramClient("gtmail_bot_session", API_ID, API_HASH)

# Active Watcher Tasks & Message Tracking
active_watchers = {}
watcher_end_times = {}
user_variant_msg_ids = {}

active_tempmail_watchers = {}
tempmail_watcher_end_times = {}
user_tempmail_msg_ids = {}

def start_gmail_auto_watcher(user_id: int, chat_id: int = None, duration_seconds: int = None, interval: float = 0.4):
    """Starts/extends a background auto-watcher to push new Telegram OTPs instantly (None = permanent 24/7)."""
    target_peer = chat_id or user_id
    loop = asyncio.get_event_loop()
    
    # Extend timer (None means infinite 24/7 watching)
    if duration_seconds is None:
        watcher_end_times[user_id] = float('inf')
    else:
        watcher_end_times[user_id] = loop.time() + duration_seconds
    
    # If already running for this user, timer is refreshed
    if user_id in active_watchers and not active_watchers[user_id].done():
        print(f"[AutoWatcher] Watcher timer refreshed for user {user_id}")
        return

    async def _watcher_loop():
        print(f"[AutoWatcher] ⚡ Ultra-Fast Watcher Started for user {user_id} (Target: {target_peer}, Interval: {interval}s)")
        gmail_acc = await get_gmail_account(user_id)
        if not gmail_acc:
            return
            
        access_token = gmail_acc["access_token"]
        refresh_tok = gmail_acc.get("refresh_token")
        last_delivered_msg_id = gmail_acc.get("last_msg_id")

        conn = aiohttp.TCPConnector(limit=5, keepalive_timeout=60)
        async with aiohttp.ClientSession(connector=conn) as session:
            while loop.time() < watcher_end_times.get(user_id, 0):
                try:
                    # Zero-delay raw timeline check
                    fast_res = await fetch_fast_latest_gmail_otp(session, access_token, known_last_msg_id=last_delivered_msg_id)
                    
                    # Handle token expiry seamlessly
                    if fast_res.get("auth_failed") and refresh_tok:
                        rf_res = await refresh_access_token(refresh_tok)
                        if rf_res.get("success"):
                            access_token = rf_res["access_token"]
                            await save_gmail_account(user_id, gmail_acc["email"], access_token, refresh_tok, rf_res["expires_in"])
                            fast_res = await fetch_fast_latest_gmail_otp(session, access_token, known_last_msg_id=last_delivered_msg_id)
                            
                    if fast_res.get("has_new"):
                        found_otp = fast_res.get("otp")
                        found_msg_id = fast_res.get("id")
                        
                        if found_otp and found_msg_id and found_msg_id != last_delivered_msg_id:
                            print(f"[AutoWatcher] ⚡ INSTANT OTP DETECTED: {found_otp} (Msg ID: {found_msg_id}) for user {user_id}")
                            last_delivered_msg_id = found_msg_id
                            await update_last_delivered_otp(user_id, found_msg_id, found_otp)
                            try:
                                otp_msg_text = f"{TG_STAR} <b>New OTP Received</b>"
                                await bot.send_message(target_peer, otp_msg_text, parse_mode="html", buttons=get_otp_delivery_menu(found_otp))
                                print(f"[AutoWatcher] ✅ Instant OTP {found_otp} sent to {target_peer}!")
                            except Exception as send_err:
                                print(f"[AutoWatcher] ❌ Error sending message to {target_peer}: {send_err}")
                except asyncio.CancelledError:
                    print(f"[AutoWatcher] Watcher cancelled for user {user_id}")
                    return
                except Exception as e:
                    print(f"[AutoWatcher] Error in loop for {user_id}: {e}")
                await asyncio.sleep(interval)

        # When finite timer expires, edit active variant message in-place to "Gmail Expired"
        if loop.time() >= watcher_end_times.get(user_id, 0) and watcher_end_times.get(user_id, 0) != float('inf'):
            print(f"[AutoWatcher] Watcher expired for user {user_id}")
            var_msg_id = user_variant_msg_ids.get(user_id)
            if var_msg_id:
                try:
                    await bot.edit_message(
                        target_peer,
                        var_msg_id,
                        "⚠️ <b>Gmail Expired</b>",
                        parse_mode="html",
                        buttons=get_gmail_expired_menu()
                    )
                    print(f"[AutoWatcher] Edited message {var_msg_id} to Gmail Expired for user {user_id}")
                except Exception as err:
                    print(f"[AutoWatcher] Error editing expired message for user {user_id}: {err}")

    task = asyncio.create_task(_watcher_loop())
    active_watchers[user_id] = task

def start_tempmail_auto_watcher(user_id: int, chat_id: int = None, duration_seconds: int = 300, interval: float = 1.8):
    """Starts/extends a background auto-watcher for TempMail OTPs with rate-limit protection."""
    target_peer = chat_id or user_id
    loop = asyncio.get_event_loop()
    
    tempmail_watcher_end_times[user_id] = loop.time() + duration_seconds
    
    if user_id in active_tempmail_watchers and not active_tempmail_watchers[user_id].done():
        print(f"[TempMailWatcher] Watcher timer refreshed for user {user_id} (5m from now)")
        return

    async def _tm_watcher_loop():
        print(f"[TempMailWatcher] ⚡ Super-Fast TempMail Watcher Started for user {user_id} (Target: {target_peer}, Interval: {interval}s)")
        conn = aiohttp.TCPConnector(limit=5, keepalive_timeout=60)
        async with aiohttp.ClientSession(connector=conn) as session:
            while loop.time() < tempmail_watcher_end_times.get(user_id, 0):
                try:
                    t_acc = await get_tempmail(user_id)
                    if not t_acc or not t_acc.get("token"):
                        break
                        
                    last_delivered_msg_id = t_acc.get("last_msg_id")
                    fast_res = await fetch_fast_tempmail_otp(session, t_acc["token"], known_last_msg_id=last_delivered_msg_id)
                    
                    if fast_res.get("has_new"):
                        found_otp = fast_res.get("otp")
                        found_msg_id = fast_res.get("id")
                        
                        if found_otp and found_msg_id and found_msg_id != last_delivered_msg_id:
                            print(f"[TempMailWatcher] ⚡ NEW OTP FOUND: {found_otp} (Msg ID: {found_msg_id}) for user {user_id}")
                            await update_last_delivered_tempmail_otp(user_id, found_msg_id, found_otp)
                            try:
                                otp_msg_text = f"{TG_STAR} <b>New OTP Received</b>"
                                await bot.send_message(target_peer, otp_msg_text, parse_mode="html", buttons=get_otp_delivery_menu(found_otp))
                                print(f"[TempMailWatcher] ✅ Successfully sent OTP {found_otp} to {target_peer}")
                            except Exception as send_err:
                                print(f"[TempMailWatcher] ❌ Error sending message to {target_peer}: {send_err}")
                except asyncio.CancelledError:
                    print(f"[TempMailWatcher] Watcher cancelled for user {user_id}")
                    return
                except Exception as e:
                    print(f"[TempMailWatcher] Error in loop for {user_id}: {e}")
                await asyncio.sleep(interval)

        # When 5-minute timer expires, edit active TempMail message in-place to "TempMail Expired"
        if loop.time() >= tempmail_watcher_end_times.get(user_id, 0):
            print(f"[TempMailWatcher] 5-min watcher expired for user {user_id}")
            tm_msg_id = user_tempmail_msg_ids.get(user_id)
            if tm_msg_id:
                try:
                    await bot.edit_message(
                        target_peer,
                        tm_msg_id,
                        "⚠️ <b>TempMail Expired</b>",
                        parse_mode="html",
                        buttons=get_tempmail_expired_menu()
                    )
                    print(f"[TempMailWatcher] Edited message {tm_msg_id} to TempMail Expired for user {user_id}")
                except Exception as err:
                    print(f"[TempMailWatcher] Error editing expired TempMail message for user {user_id}: {err}")

    task = asyncio.create_task(_tm_watcher_loop())
    active_tempmail_watchers[user_id] = task

# ==================== HELPER SENDERS ====================

async def send_welcome_messages(event):
    # Message 1: Welcome Banner (First)
    welcome_text = f"{TG_DIAMOND} <b>Welcome</b>\n\nNeed Support?\nNeed Any Bot Make?\n\nChoose an option below."
    await event.respond(welcome_text, parse_mode="html", buttons=get_start_inline_menu())
    
    # Message 2: Persistent Menu (Second)
    menu_text = f"{TG_STAR} Use the persistent menu below to navigate features:"
    await event.respond(menu_text, parse_mode="html", buttons=get_main_persistent_menu())

# ==================== COMMAND & MESSAGE HANDLERS ====================

@bot.on(events.NewMessage(pattern=r"^/start"))
async def start_handler(event):
    user = await event.get_sender()
    await set_user_state(user.id, state=None, data={}, first_name=user.first_name or "", username=user.username or "")
    await send_welcome_messages(event)

@bot.on(events.NewMessage)
async def message_dispatcher(event):
    if event.raw_text.startswith("/start"):
        return
        
    text = event.raw_text.strip()
    user_id = event.sender_id
    state, sdata = await get_user_state(user_id)
    
    # 1. PERSISTENT MENU BUTTONS (ALWAYS TAKE PRECEDENCE & CANCEL PENDING STATES)
    PERSISTENT_BUTTONS = ["📧 Gmail", "💌 TempMail", "📄 Gmail Format", "🗑 Remove Gmail", "👨‍💻 Developer"]
    if text in PERSISTENT_BUTTONS:
        await set_user_state(user_id, state=None, data={})
        
        if text == "📧 Gmail":
            gmail_acc = await get_gmail_account(user_id)
            if gmail_acc:
                msg_text = f"{TG_DIAMOND} <b>Gmail Manager</b>\n\nLinked Account: <code>{gmail_acc['email']}</code>"
                await event.respond(msg_text, parse_mode="html", buttons=get_gmail_inline_menu(logged_in=True))
            else:
                msg_text = f"{TG_DIAMOND} <b>Gmail Manager</b>\n\nManage your personal linked Gmail account securely."
                await event.respond(msg_text, parse_mode="html", buttons=get_gmail_inline_menu(logged_in=False))

        elif text == "💌 TempMail":
            t_acc = await get_tempmail(user_id)
            if not t_acc:
                new_acc = await create_tempmail_account()
                if new_acc.get("success"):
                    await save_tempmail(user_id, new_acc["email"], new_acc["token"], new_acc["password"])
                    t_acc = new_acc
                else:
                    await event.respond("❌ TempMail service is temporarily busy. Please try again.")
                    return
                    
            email = t_acc["email"]
            msg_text = f"{TG_DIAMOND} <b>TempMail Inbox Ready</b>"
            sent_msg = await event.respond(msg_text, parse_mode="html", buttons=get_tempmail_inline_menu(email))
            user_tempmail_msg_ids[user_id] = sent_msg.id
            
            # Start TempMail 5-minute auto-watcher
            start_tempmail_auto_watcher(user_id, event.chat_id, duration_seconds=300, interval=1.8)

        elif text == "📄 Gmail Format":
            await set_user_state(user_id, state="FORMAT_STEP_1_EMAIL", data={})
            step1_text = f"{TG_DIAMOND} <b>Step 1/2:</b> Please send your base Gmail address (e.g. <code>example@gmail.com</code>):"
            await event.respond(step1_text, parse_mode="html")

        elif text == "🗑 Remove Gmail":
            await delete_gmail_account(user_id)
            msg_text = f"{TG_TRASH} Gmail account mapping and token successfully removed."
            await event.respond(msg_text, parse_mode="html", buttons=get_main_persistent_menu())

        elif text == "👨‍💻 Developer":
            msg_text = f"{TG_DIAMOND} <b>Contact Developer</b>\n\nTap below to reach out."
            await event.respond(msg_text, parse_mode="html", buttons=get_dev_menu())
        return

    # 2. STATE HANDLERS (ONLY FOR WIZARDS / OAUTH URL PASTE)
    is_oauth_url = "code=" in text or "http://localhost" in text or text.startswith("4/0A")
    if state == "AWAITING_GOOGLE_CODE" or is_oauth_url:
        status_msg = await event.respond("⏳ <i>Connecting your Gmail account...</i>", parse_mode="html")
        token_res = await exchange_code_for_tokens(text)
        
        if token_res.get("success"):
            acc_token = token_res["access_token"]
            ref_token = token_res["refresh_token"]
            exp_in = token_res["expires_in"]
            email = token_res.get("email")
            
            if not email:
                prof = await get_user_gmail_profile(acc_token)
                email = prof.get("email", "Linked Gmail") if prof.get("success") else "Linked Gmail"
            
            await save_gmail_account(user_id, email, acc_token, ref_token, exp_in)
            await set_user_state(user_id, state=None, data={})
            
            success_txt = f"{TG_KEY} <b>Gmail Connected Successfully!</b>\n\nAccount: <code>{email}</code>\n\nYou can now click <b>📧 Generate Gmail</b> to create variations and receive incoming Telegram codes automatically."
            try:
                await status_msg.edit(success_txt, parse_mode="html", buttons=get_gmail_inline_menu(logged_in=True))
            except:
                await event.respond(success_txt, parse_mode="html", buttons=get_gmail_inline_menu(logged_in=True))
        else:
            err_msg = token_res.get("error", "Invalid code or token error")
            fail_txt = f"{TG_EMPTY} <b>OAuth Login Failed!</b>\n\nError: <code>{err_msg}</code>\n\nPlease tap <b>🔑 Start Google OAuth Login</b> to get a fresh login link."
            try:
                await status_msg.edit(fail_txt, parse_mode="html", buttons=get_gmail_inline_menu(logged_in=False))
            except:
                await event.respond(fail_txt, parse_mode="html", buttons=get_gmail_inline_menu(logged_in=False))
            await set_user_state(user_id, state=None, data={})
        return

    elif state == "FORMAT_STEP_1_EMAIL":
        if "@" not in text or "." not in text:
            await event.respond(f"{TG_WARN} Please provide a valid email format (e.g. <code>example@gmail.com</code>):", parse_mode="html")
            return
        
        await set_user_state(user_id, state="FORMAT_STEP_2_QTY", data={"base_email": text})
        step2_text = f"{TG_DIAMOND} <b>Step 2/2:</b> Send the quantity to generate (e.g. <code>5</code>, <code>10</code>, <code>50</code>):"
        await event.respond(step2_text, parse_mode="html")
        return

    elif state == "FORMAT_STEP_2_QTY":
        if not text.isdigit() or int(text) <= 0:
            await event.respond(f"{TG_WARN} Please send a valid positive number (e.g. <code>10</code>):", parse_mode="html")
            return
            
        qty = min(int(text), 1000)
        base_email = sdata.get("base_email", "example@gmail.com")
        variants = generate_gmail_variants(base_email, quantity=qty)
        
        await set_user_state(user_id, state=None, data={"last_variants": variants, "base_email": base_email})
        
        preview_count = min(qty, 10)
        preview_lines = [f"<code>{v}</code>" for v in variants[:preview_count]]
        if qty > 10:
            preview_lines.append(f"<i>... and {qty - 10} more in TXT file</i>")
        preview_list = "\n".join(preview_lines)
            
        out_msg = (
            f"{TG_STAR} <b>Generated Variants</b> ({qty} total)\n\n"
            f"{preview_list}\n\n"
            f"💡 <i>Tap any email above to copy it individually!</i>"
        )
        await event.respond(out_msg, parse_mode="html", buttons=get_format_export_menu(qty))
        return

# ==================== CALLBACK QUERY HANDLERS ====================

@bot.on(events.CallbackQuery)
async def callback_dispatcher(event):
    data = event.data.decode("utf-8", errors="ignore")
    user_id = event.sender_id
    
    # 1. GMAIL OAUTH LOGIN
    if data == "gmail_login":
        auth_url = get_google_auth_url(state=str(user_id))
        await set_user_state(user_id, state="AWAITING_GOOGLE_CODE", data={})
        
        login_prompt = f"{TG_KEY} <b>Google OAuth Login</b>\n\n1. Click the button below to authorize.\n2. After granting permission, copy the full <code>http://localhost/?code=...</code> URL from your browser address bar.\n3. Send that URL directly back here in chat."
        gmail_acc = await get_gmail_account(user_id)
        await event.respond(login_prompt, parse_mode="html", buttons=get_gmail_inline_menu(logged_in=bool(gmail_acc), login_url=auth_url))
        await event.answer()

    # 2. GENERATE GMAIL VARIANTS (2 COPIABLE VARIANTS ONLY, 5-MIN WATCHER, EXPIRES IN-PLACE)
    elif data in ("get_generate_gmail", "restart_auto_watcher"):
        gmail_acc = await get_gmail_account(user_id)
        if not gmail_acc:
            no_acc_text = f"{TG_WARN} <b>No Gmail Connected!</b>\n\nPlease login first using Google OAuth to generate your Gmail."
            await event.respond(no_acc_text, parse_mode="html", buttons=get_gmail_inline_menu(logged_in=False))
            await event.answer()
            return
            
        base_email = gmail_acc["email"]
        # Generate 2 fresh random variants
        variants = generate_gmail_variants(base_email, quantity=2)
        await set_user_state(user_id, state=None, data={"last_variants": variants, "base_email": base_email})
        
        # Delete old message (e.g. variants message or expired message)
        try:
            await event.delete()
        except Exception:
            pass

        out_msg = f"{TG_STAR} <b>Generated variants</b>"
        
        # Send new message with 2 copy buttons for the 2 variants
        sent_msg = await bot.send_message(
            event.chat_id or user_id,
            out_msg,
            parse_mode="html",
            buttons=get_gmail_copy_variants_menu(variants)
        )
        user_variant_msg_ids[user_id] = sent_msg.id
        
        # Start 5-minute background auto-watcher for incoming OTPs
        start_gmail_auto_watcher(user_id, event.chat_id or user_id, duration_seconds=300, interval=0.4)
        
        await event.answer("Generated variants!")

    # 3. REFRESH GMAIL OTP (INSTANT ZERO-DELAY TIMELINE CHECK)
    elif data == "refresh_gmail_otp":
        gmail_acc = await get_gmail_account(user_id)
        if not gmail_acc:
            await event.respond("<code>No Gmail login found</code>", parse_mode="html")
            await event.answer()
            return
            
        start_gmail_auto_watcher(user_id, event.chat_id or user_id, duration_seconds=300, interval=0.4)
            
        access_token = gmail_acc["access_token"]
        last_delivered_msg_id = gmail_acc.get("last_msg_id")
        
        conn = aiohttp.TCPConnector(limit=5, keepalive_timeout=60)
        async with aiohttp.ClientSession(connector=conn) as session:
            fast_res = await fetch_fast_latest_gmail_otp(session, access_token, known_last_msg_id=last_delivered_msg_id)
            if fast_res.get("auth_failed") and gmail_acc.get("refresh_token"):
                rf_res = await refresh_access_token(gmail_acc["refresh_token"])
                if rf_res.get("success"):
                    access_token = rf_res["access_token"]
                    await save_gmail_account(user_id, gmail_acc["email"], access_token, gmail_acc["refresh_token"], rf_res["expires_in"])
                    fast_res = await fetch_fast_latest_gmail_otp(session, access_token, known_last_msg_id=last_delivered_msg_id)

        if fast_res.get("has_new"):
            found_otp = fast_res.get("otp")
            found_msg_id = fast_res.get("id")
            if found_otp and found_msg_id and found_msg_id != last_delivered_msg_id:
                await update_last_delivered_otp(user_id, found_msg_id, found_otp)
                otp_msg_text = f"{TG_STAR} <b>New OTP Received</b>"
                await event.respond(otp_msg_text, parse_mode="html", buttons=get_otp_delivery_menu(found_otp))
            else:
                await event.respond("📭 No new code found", parse_mode="html")
        else:
            await event.respond("📭 No code found", parse_mode="html")
                
        await event.answer()

    # 4. CHANGE TEMPMAIL / RESTART TEMPMAIL (NEW TEMPMAIL & DELETE PREVIOUS MESSAGE)
    elif data in ("change_tempmail", "restart_tempmail_watcher"):
        try:
            await event.delete()
        except Exception:
            pass

        new_acc = await create_tempmail_account()
        if new_acc.get("success"):
            await save_tempmail(user_id, new_acc["email"], new_acc["token"], new_acc["password"])
            email = new_acc["email"]
            msg_text = f"{TG_DIAMOND} <b>TempMail Inbox Ready</b>"
            sent_msg = await bot.send_message(
                event.chat_id or user_id,
                msg_text,
                parse_mode="html",
                buttons=get_tempmail_inline_menu(email)
            )
            user_tempmail_msg_ids[user_id] = sent_msg.id
            
            # Start auto-watcher for new tempmail
            start_tempmail_auto_watcher(user_id, event.chat_id or user_id, duration_seconds=300, interval=1.8)
        else:
            await event.respond("❌ Failed to create new TempMail. Please try again.")
        await event.answer()

    # 5. REFRESH TEMPMAIL OTP
    elif data == "refresh_tempmail":
        t_acc = await get_tempmail(user_id)
        if not t_acc or not t_acc.get("token"):
            await event.respond(f"{TG_WARN} No active TempMail found. Tap 💌 TempMail to generate one.", parse_mode="html")
            await event.answer()
            return
            
        start_tempmail_auto_watcher(user_id, event.chat_id or user_id, duration_seconds=300, interval=1.8)
        messages = await fetch_tempmail_messages(t_acc["token"])
        
        found_otp = None
        found_msg_id = None
        for m in messages:
            if m.get("otp"):
                found_otp = m["otp"]
                found_msg_id = m.get("id")
                break
                
        last_delivered_otp = t_acc.get("last_otp")
        last_delivered_msg_id = t_acc.get("last_msg_id")
        
        if found_otp:
            if found_otp == last_delivered_otp or (found_msg_id and found_msg_id == last_delivered_msg_id):
                await event.respond("📭 No new code found", parse_mode="html")
            else:
                await update_last_delivered_tempmail_otp(user_id, found_msg_id or "", found_otp)
                otp_msg_text = f"{TG_STAR} <b>New OTP Received</b>"
                await event.respond(otp_msg_text, parse_mode="html", buttons=get_otp_delivery_menu(found_otp))
        else:
            await event.respond("📭 No code found", parse_mode="html")
        await event.answer()

    # 6. EXPORT FORMAT AS TXT FILE
    elif data.startswith("format_txt_"):
        _, sdata = await get_user_state(user_id)
        variants = sdata.get("last_variants", [])
        if not variants:
            await event.respond(f"{TG_WARN} No variants found in cache. Please generate again.", parse_mode="html")
            await event.answer()
            return
            
        file_bytes = "\n".join(variants).encode("utf-8")
        file_obj = io.BytesIO(file_bytes)
        file_obj.name = "gmail_variants.txt"
        
        await bot.send_file(
            event.chat_id,
            file_obj,
            caption=f"📄 <b>Gmail Variants Export</b>\nTotal: <code>{len(variants)}</code> emails",
            parse_mode="html"
        )
        await event.answer("TXT file generated!")

    # 7. EXPORT FORMAT AS RAW TEXT
    elif data == "format_raw":
        _, sdata = await get_user_state(user_id)
        variants = sdata.get("last_variants", [])
        if not variants:
            await event.respond(f"{TG_WARN} No variants found in cache. Please generate again.", parse_mode="html")
            await event.answer()
            return
            
        raw_text = "\n".join(variants)
        await event.respond(f"<code>{raw_text}</code>", parse_mode="html")
        await event.answer("Raw text sent!")

# ==================== BOT STARTUP ====================

async def start_all_permanent_watchers():
    all_accounts = await get_all_gmail_accounts()
    print(f"[Startup] Restoring 24/7 background watchers for {len(all_accounts)} connected Gmail account(s)...")
    for acc in all_accounts:
        user_id = acc["user_id"]
        start_gmail_auto_watcher(user_id, duration_seconds=None, interval=0.4)
        if GOOGLE_PUBSUB_TOPIC and acc.get("access_token"):
            w_res = await setup_gmail_watch(acc["access_token"], GOOGLE_PUBSUB_TOPIC)
            print(f"[Startup] Gmail watch for user {user_id} setup status: {w_res.get('success')}")

async def main():
    print("Initializing Database...")
    await init_db()
    
    if not BOT_TOKEN or BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN":
        raise ValueError("❌ BOT_TOKEN is missing or invalid in your .env file! Please set BOT_TOKEN in .env")
        
    print("Starting Telethon Bot...")
    await bot.start(bot_token=BOT_TOKEN)
    me = await bot.get_me()
    print(f"Bot started successfully as @{me.username} ({me.first_name})")
    
    # Restore permanent 24/7 watchers for all connected accounts
    await start_all_permanent_watchers()

    # Start Webhook HTTP Server
    app = create_webhook_app(bot_instance=bot)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, WEBHOOK_HOST, WEBHOOK_PORT)
    await site.start()
    print(f"🚀 Webhook HTTP Server running at http://{WEBHOOK_HOST}:{WEBHOOK_PORT}/ (Endpoints: POST /webhook/gmail | POST /webhook/tempmail)")

    await bot.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
