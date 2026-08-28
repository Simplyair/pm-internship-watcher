"""Telegram Bot API client: alerts with inline triage buttons."""
from __future__ import annotations

import html

from .http import FetchError, post_json

API = "https://api.telegram.org/bot{token}/{method}"

# Buttons attached to every alert. callback_data must stay under 64 bytes.
BUTTONS = (
    ("Applied", "applied"),
    ("Save", "saved"),
    ("Ignore", "ignored"),
)

STATUS_EMOJI = {
    "new": "*", "saved": "[S]", "applied": "[A]", "interview": "[I]",
    "offer": "[O]", "rejected": "[R]", "ignored": "[x]",
}


class Telegram:
    def __init__(self, token: str, chat_id: str = ""):
        if not token:
            raise ValueError("TELEGRAM_BOT_TOKEN is not set (see .env.example)")
        self.token = token
        self.chat_id = chat_id

    def call(self, method: str, payload: dict | None = None) -> dict:
        data = post_json(API.format(token=self.token, method=method), payload or {})
        if not data.get("ok"):
            raise FetchError(f"telegram {method} failed: {data}")
        return data.get("result", {})

    # --- basics ------------------------------------------------------------

    def me(self) -> dict:
        return self.call("getMe")

    def send(self, text: str, reply_markup: dict | None = None,
             disable_preview: bool = True) -> dict:
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": disable_preview,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return self.call("sendMessage", payload)

    def get_updates(self, offset: int = 0, timeout: int = 0) -> list[dict]:
        payload = {"timeout": timeout, "allowed_updates": ["message", "callback_query"]}
        if offset:
            payload["offset"] = offset
        return self.call("getUpdates", payload)

    def answer_callback(self, callback_id: str, text: str = "") -> None:
        try:
            self.call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})
        except FetchError:
            pass  # the spinner timing out is not worth failing a scan over

    def edit_markup(self, message_id: int, reply_markup: dict | None) -> None:
        try:
            self.call("editMessageReplyMarkup", {
                "chat_id": self.chat_id,
                "message_id": message_id,
                "reply_markup": reply_markup or {"inline_keyboard": []},
            })
        except FetchError:
            pass  # message too old to edit, or unchanged

    def edit_text(self, message_id: int, text: str, reply_markup: dict | None = None) -> None:
        try:
            payload = {
                "chat_id": self.chat_id, "message_id": message_id, "text": text,
                "parse_mode": "HTML", "disable_web_page_preview": True,
            }
            if reply_markup is not None:
                payload["reply_markup"] = reply_markup
            self.call("editMessageText", payload)
        except FetchError:
            pass


# --- message construction --------------------------------------------------

def esc(text: str) -> str:
    return html.escape(text or "", quote=False)


def job_message(job, region: str = "") -> str:
    """Format one posting as an HTML Telegram message."""
    lines = [f"<b>{esc(job.company)}</b>", esc(job.title)]
    meta = []
    if job.location:
        meta.append(esc(job.location))
    if region in ("ca", "na"):
        meta.append("CA")
    if meta:
        lines.append(" | ".join(meta))
    if job.posted_at:
        lines.append(f"posted {esc(job.posted_at[:10])}")
    if job.url:
        lines.append(f'\n<a href="{esc(job.url)}">Open posting</a>')
    return "\n".join(lines)


def job_keyboard(key: str, url: str = "") -> dict:
    row = [{"text": label, "callback_data": f"s:{status}:{key}"}
           for label, status in BUTTONS]
    keyboard = [row]
    if url:
        keyboard.insert(0, [{"text": "Apply", "url": url}])
    return {"inline_keyboard": keyboard}


def decided_keyboard(status: str, url: str = "") -> dict:
    """Replace the button row once a decision is recorded."""
    keyboard = []
    if url:
        keyboard.append([{"text": "Apply", "url": url}])
    keyboard.append([{"text": f"-- {status} --", "callback_data": "noop"}])
    return {"inline_keyboard": keyboard}
