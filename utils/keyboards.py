from telethon.tl.types import (
    ReplyKeyboardMarkup,
    KeyboardButtonRow,
    KeyboardButton,
    ReplyInlineMarkup,
    KeyboardButtonRow as InlineRow,
    KeyboardButtonCallback,
    KeyboardButtonUrl,
    KeyboardButtonCopy,
    KeyboardButtonStyle
)
from config import DEV_USERNAME, CHANNEL_URL

STYLE_PRIMARY = KeyboardButtonStyle(bg_primary=True)
STYLE_SUCCESS = KeyboardButtonStyle(bg_success=True)
STYLE_DANGER = KeyboardButtonStyle(bg_danger=True)

def get_main_persistent_menu():
    return ReplyKeyboardMarkup(
        rows=[
            KeyboardButtonRow(buttons=[
                KeyboardButton(text="📧 Gmail", style=STYLE_PRIMARY),
                KeyboardButton(text="💌 TempMail", style=STYLE_PRIMARY)
            ]),
            KeyboardButtonRow(buttons=[
                KeyboardButton(text="📄 Gmail Format", style=STYLE_SUCCESS),
                KeyboardButton(text="🗑 Remove Gmail", style=STYLE_DANGER)
            ]),
            KeyboardButtonRow(buttons=[
                KeyboardButton(text="👨‍💻 Developer", style=STYLE_PRIMARY)
            ])
        ],
        resize=True
    )

def get_start_inline_menu():
    return ReplyInlineMarkup(
        rows=[
            InlineRow(buttons=[
                KeyboardButtonUrl(text="👨‍💻 Developer", url=f"https://t.me/{DEV_USERNAME}", style=STYLE_PRIMARY),
                KeyboardButtonUrl(text="📢 Channel", url=CHANNEL_URL, style=STYLE_SUCCESS)
            ])
        ]
    )

def get_gmail_inline_menu(logged_in: bool = False, login_url: str = None):
    buttons = []
    if login_url:
        buttons.append(InlineRow(buttons=[
            KeyboardButtonUrl(text="🔐 Open Google Login", url=login_url, style=STYLE_PRIMARY)
        ]))
    elif logged_in:
        buttons.append(InlineRow(buttons=[
            KeyboardButtonCallback(text="✅ Logged in successfully", data=b"gmail_login", style=STYLE_SUCCESS)
        ]))
    else:
        buttons.append(InlineRow(buttons=[
            KeyboardButtonCallback(text="🔑 Start Google OAuth Login", data=b"gmail_login", style=STYLE_PRIMARY)
        ]))
    
    buttons.append(InlineRow(buttons=[
        KeyboardButtonCallback(text="⚡ Generate Gmail", data=b"get_generate_gmail", style=STYLE_PRIMARY)
    ]))
    
    return ReplyInlineMarkup(rows=buttons)

def get_gmail_copy_variants_menu(variants: list):
    """Menu for Generate Gmail with copy buttons for each variant and Generate New Gmail (left) + Refresh OTP (right) in same row."""
    rows = []
    for v in variants:
        rows.append(InlineRow(buttons=[
            KeyboardButtonCopy(text=f"📧 {v}", copy_text=v, style=STYLE_PRIMARY)
        ]))
    rows.append(InlineRow(buttons=[
        KeyboardButtonCallback(text="🔄 Generate New Gmail", data=b"get_generate_gmail", style=STYLE_SUCCESS),
        KeyboardButtonCallback(text="📥 Refresh OTP", data=b"refresh_gmail_otp", style=STYLE_PRIMARY)
    ]))
    return ReplyInlineMarkup(rows=rows)

def get_gmail_expired_menu():
    """Menu when Gmail variants expire after 5 mins."""
    return ReplyInlineMarkup(
        rows=[
            InlineRow(buttons=[
                KeyboardButtonCallback(text="🔄 Generate New Gmail", data=b"get_generate_gmail", style=STYLE_PRIMARY)
            ])
        ]
    )

def get_tempmail_inline_menu(email: str):
    return ReplyInlineMarkup(
        rows=[
            InlineRow(buttons=[
                KeyboardButtonCopy(text=f"💌 {email}", copy_text=email, style=STYLE_PRIMARY)
            ]),
            InlineRow(buttons=[
                KeyboardButtonCallback(text="🔄 Change TempMail", data=b"change_tempmail", style=STYLE_SUCCESS)
            ])
        ]
    )

def get_tempmail_expired_menu():
    """Menu when TempMail expires after 5 mins."""
    return ReplyInlineMarkup(
        rows=[
            InlineRow(buttons=[
                KeyboardButtonCallback(text="🔄 Generate New", data=b"change_tempmail", style=STYLE_PRIMARY)
            ])
        ]
    )

def get_otp_delivery_menu(otp: str):
    """Menu for delivering OTP inside a bg_primary colored copy button."""
    return ReplyInlineMarkup(
        rows=[
            InlineRow(buttons=[
                KeyboardButtonCopy(text=f"🔑 {otp}", copy_text=otp, style=STYLE_PRIMARY)
            ])
        ]
    )

def get_format_export_menu(qty: int):
    """Menu for Gmail Format Wizard with TXT & RAW buttons"""
    return ReplyInlineMarkup(
        rows=[
            InlineRow(buttons=[
                KeyboardButtonCallback(text="📄 TXT File", data=f"format_txt_{qty}".encode("utf-8"), style=STYLE_PRIMARY),
                KeyboardButtonCallback(text="📜 RAW Text", data=b"format_raw", style=STYLE_SUCCESS)
            ])
        ]
    )

def get_dev_menu():
    return ReplyInlineMarkup(
        rows=[
            InlineRow(buttons=[
                KeyboardButtonUrl(text="👨‍💻 Developer", url=f"https://t.me/{DEV_USERNAME}", style=STYLE_PRIMARY)
            ])
        ]
    )
