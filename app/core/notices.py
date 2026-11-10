"""The cancellation email to the merchant (D-104). Demo only: no real email is ever sent.

Order: PayPal cancel first (actions.py) -> `create_draft` (LLM, validated here; template on failure) -> the user
edits it in the preview -> `finalize` with "Send" (saved to data/runtime/outbox/) or "Open in Gmail" (a compose
link with her edited text). Nothing is sent without her click; a second click returns the email already sent.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import secrets
from typing import Literal
from urllib.parse import quote

from pydantic import BaseModel

from app.core.policy import Decision
from app.core.services import Services
from app.llm.base import EmailDraft, LLMError, NoticeContext
from app.models import Notice, Subscription
from app.store import atomic_write_text, ts_slug, utcnow

log = logging.getLogger("subguard.notices")
MAX_WORDS = 120
GMAIL_MAX_URL = 1800
GMAIL_BASE = "https://mail.google.com/mail/?view=cm&fs=1"
TEMPLATE_LABEL = "standard template"
SentVia = Literal["demo_outbox", "gmail_compose_link"]


def word_count(text: str) -> int:
    return len(re.findall(r"\S+", text))


def notice_clause(svc: Services, sub: Subscription) -> str:
    """The verbatim NOTICE_PERIOD quote from the stored review ("" if the review has none)."""
    from app.core.timers import review_for  # timers imports actions, which imports this module

    review = review_for(svc, sub)
    clause = next((c for c in review.data.clauses if c.type == "NOTICE_PERIOD"), None) if review else None
    return clause.quote if clause else ""


def notice_context(svc: Services, sub: Subscription) -> NoticeContext:
    user = svc.user(sub.owner_id)
    merchant = svc.merchant(sub.merchant_id)
    return NoticeContext(user_name=user.name if user else sub.owner_id, account_email=user.email if user else "",
                         merchant_name=merchant.name, to=merchant.support_email, paypal_id=sub.paypal_id,
                         date_text=utcnow().strftime("%d %B %Y").lstrip("0"), clause=notice_clause(svc, sub))


def validate_draft(draft: EmailDraft, ctx: NoticeContext) -> list[str]:
    """Code, not the model, decides if a draft is usable. Returns the problems ([] = OK)."""
    body = draft.body
    problems = [] if draft.subject.strip() else ["empty subject"]
    for label, value in (("name", ctx.user_name), ("account email", ctx.account_email),
                         ("PayPal subscription ID", ctx.paypal_id), ("date", ctx.date_text)):
        if value and value not in body:
            problems.append(f"missing {label}")
    if ctx.clause and ctx.clause not in body:
        problems.append("cancellation clause not quoted verbatim")
    low = body.lower()
    if "cancel" not in low or "confirm" not in low or "writing" not in low:
        problems.append("no request to cancel and confirm in writing")
    if word_count(body) >= MAX_WORDS:
        problems.append(f"{word_count(body)} words (must be under {MAX_WORDS})")
    if re.search(r"https?://|www\.", low):
        problems.append("contains a link")
    return problems


def template_draft(ctx: NoticeContext) -> EmailDraft:
    quote_line = f'Your terms say: "{ctx.clause}"\n\n' if ctx.clause else ""
    body = (f"Hello {ctx.merchant_name} team,\n\nPlease cancel my subscription.\n\n"
            f"Name: {ctx.user_name}\nAccount email: {ctx.account_email}\n"
            f"PayPal subscription ID: {ctx.paypal_id}\nDate: {ctx.date_text}\n\n{quote_line}"
            "Please treat this email as my written notice, cancel the subscription and confirm the cancellation "
            f"in writing.\n\nThank you,\n{ctx.user_name}")
    return EmailDraft(subject=f"Cancellation of subscription {ctx.paypal_id}", body=body)


def notice_for(svc: Services, sub_id: str) -> Notice | None:
    return next((n for n in svc.store.load("notices").items if n.subscription_id == sub_id), None)


async def create_draft(svc: Services, sub: Subscription, *, by_timer: bool = False) -> Notice:
    """Draft (never send) the cancellation email. Idempotent per subscription."""
    if (existing := notice_for(svc, sub.id)) is not None:
        return existing
    ctx = notice_context(svc, sub)
    llm = svc.llm
    draft, problems, label = None, [], TEMPLATE_LABEL
    if llm is not None:
        try:
            draft = await llm.draft_cancellation_notice(ctx)
            problems = validate_draft(draft, ctx)
            label = f"{llm.name} · {llm.model}"
        except LLMError as exc:
            problems = [f"LLM error: {exc}"]
        except Exception as exc:  # noqa: BLE001 - any provider failure falls back to the template
            log.warning(f"draft failed: {type(exc).__name__}")
            problems = [f"LLM error: {type(exc).__name__}"]
    source: Literal["llm", "template"] = "llm"
    if draft is None or problems:
        draft, source, label = template_draft(ctx), "template", TEMPLATE_LABEL
    notice = Notice(id=f"nt-{secrets.token_hex(5)}", subscription_id=sub.id, merchant_id=sub.merchant_id,
                    sim_day=svc.day, to=ctx.to, subject=draft.subject, body=draft.body,
                    sha256=hashlib.sha256(draft.body.encode("utf-8")).hexdigest(), drafted_by=label,
                    draft_source=source, draft_problems=problems, draft_to=ctx.to, draft_subject=draft.subject,
                    draft_body=draft.body, created_at=utcnow(), by_timer=by_timer)
    async with svc.store.aedit("notices") as notices:
        if (existing := next((n for n in notices.items if n.subscription_id == sub.id), None)) is not None:
            return existing
        notices.items.append(notice)
    svc.store.audit.append(actor="agent" if source == "llm" else "system", event="cancellation_email_drafted",
                           user_id=sub.owner_id, subscription_id=sub.id, result=source,
                           details={"notice_id": notice.id, "drafted_by": label, "problems": problems,
                                    "sha256": notice.sha256, "words": word_count(notice.body)})
    return notice


def gmail_url(to: str, subject: str, body: str) -> str:
    """Gmail compose link, URL-encoded like JavaScript's encodeURIComponent."""
    q = lambda s: quote(s, safe="-_.!~*'()")  # noqa: E731
    return f"{GMAIL_BASE}&to={q(to)}&su={q(subject)}&body={q(body)}"


class EmailIn(BaseModel):
    to: str
    subject: str
    body: str


class FinalizeResult(BaseModel):
    notice: Notice
    already_sent: bool = False
    url: str | None = None
    too_long: bool = False


async def finalize(svc: Services, user_id: str, notice_id: str, email: EmailIn,
                   via: SentVia) -> FinalizeResult | Decision:
    """The user's click: "Send" (demo outbox) or "Open in Gmail". Raises ValueError on an empty To / Body."""
    current = next((n for n in svc.store.load("notices").items if n.id == notice_id), None)
    sub = svc.sub(current.subscription_id) if current else None
    if current is None or sub is None or sub.owner_id != user_id:
        return svc.policy.record(svc.store, Decision(allowed=False, rule_id="R5", reason="Not your email",
                                                     subscription_id=sub.id if sub else None),
                                 user_id=user_id, action=f"email:{via}", requested_by="user")
    if current.status == "sent":
        return FinalizeResult(notice=current, already_sent=True,
                              url=gmail_url(current.to, current.subject, current.body))
    to, subject, body = email.to.strip(), email.subject.strip(), email.body.strip()
    if not to or not body:
        raise ValueError("To and Body are required")
    if "@" not in to:
        raise ValueError("To must be an email address")
    url = gmail_url(to, subject, body)
    if via == "gmail_compose_link" and len(url) > GMAIL_MAX_URL:
        return FinalizeResult(notice=current, too_long=True)
    async with svc.store.aedit("notices") as notices:
        n = next(x for x in notices.items if x.id == notice_id)
        if n.status == "sent":  # a concurrent second click won
            return FinalizeResult(notice=n, already_sent=True, url=gmail_url(n.to, n.subject, n.body))
        n.edited = (to, subject, body) != (n.draft_to, n.draft_subject.strip(), n.draft_body.strip())
        n.to, n.subject, n.body = to, subject, body
        n.sha256 = hashlib.sha256(body.encode("utf-8")).hexdigest()
        n.status, n.sent_via, n.delivery, n.sent_at, n.sim_day = "sent", via, via, utcnow(), svc.day
        notice = n
    payload = {"type": "merchant_cancellation", "demo_only": True, "to": notice.to, "subject": notice.subject,
               "body": notice.body, "edited": notice.edited, "sha256": notice.sha256, "sent_via": via,
               "sent_at": notice.sent_at.isoformat() if notice.sent_at else None, "notice_id": notice.id,
               "subscription_id": notice.subscription_id, "drafted_by": notice.drafted_by}
    atomic_write_text(svc.notifier.outbox / f"{ts_slug()}-merchant_cancellation-{via}-{notice.id}.json",
                      json.dumps(payload, indent=2))
    svc.store.audit.append(actor="user", event="cancellation_email_sent" if via == "demo_outbox"
                           else "cancellation_email_gmail_opened", user_id=user_id,
                           subscription_id=notice.subscription_id, result=via,
                           details={"notice_id": notice.id, "to": notice.to, "edited": notice.edited,
                                    "sha256": notice.sha256, "demo_only": True})
    return FinalizeResult(notice=notice, url=url)
