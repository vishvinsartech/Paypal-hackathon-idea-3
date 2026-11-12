"""10-day trial deadline maths + the cancellation email (D-104): draft -> validate -> template fallback ->
preview -> Send (demo outbox) / Open in Gmail. PayPal is cancelled first; nothing is sent without a click."""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from app.core.notices import GMAIL_MAX_URL, gmail_url, template_draft, validate_draft
from app.core.risk import compute_deadlines
from app.core.services import Services
from app.llm.base import EmailDraft, LLMError, NoticeContext
from app.pricing import Pricing
from tests.story_helpers import add_user, advance_to, alerts, audit, cancel_via_alert, sub, subscribe
from tests.test_llm_providers import a_msg, make, o_msg

CLAUSE = ("Cancellation requires written notice by email to cancel@penwright.example at least 3 days before the "
          "next billing date.")
CTX = NoticeContext(user_name="Priya", account_email="priya@subguard-demo.example", merchant_name="Penwright Studio",
                    to="cancel@penwright.example", paypal_id="I-ABC123", date_text="10 November 2026", clause=CLAUSE)


def svc_of(c: TestClient) -> Services:
    return c.app.state.services  # type: ignore[attr-defined,no-any-return]


def outbox_emails(c: TestClient) -> list[dict[str, Any]]:
    files = sorted(svc_of(c).notifier.outbox.glob("*merchant_cancellation*.json"))
    return [json.loads(f.read_text(encoding="utf-8")) for f in files]


def cancel_on_day5(c: TestClient) -> tuple[dict[str, Any], dict[str, Any]]:
    main = subscribe(c)
    advance_to(c, 5)
    (check,) = alerts(c, kind="reminder")
    _, done = cancel_via_alert(c, check)
    assert done["all_ok"]
    notice = next(n for n in c.get("/api/notices?user=priya").json() if n["subscription_id"] == main["id"])
    assert done["results"][0]["notice_id"] == notice["id"]
    return main, notice


def post_email(c: TestClient, notice: dict[str, Any], kind: str = "send", **edit: str) -> Any:
    body = {"user_id": "priya", "to": notice["to"], "subject": notice["subject"], "body": notice["body"], **edit}
    return c.post(f"/api/notices/{notice['id']}/{kind}", json=body)


# ---- the new trial terms ------------------------------------------------------------------------------------------
def test_ten_day_trial_deadline_maths() -> None:
    p = Pricing()
    assert (p.penwright_trial_days, p.penwright_first_charge_day, p.penwright_notice_days) == (10, 11, 3)
    d = compute_deadlines(0, p.penwright_first_charge_day, p.penwright_notice_days, layer2=False)
    assert (d.real_cancel_deadline_day, d.timer_fire_day, d.reminder_day) == (7, 6, 5)  # 11 - 3 - 1 = 7
    trial, intro, regular = p.plans_for("penwright")[0].billing_cycles
    assert (trial.interval_unit, trial.interval_count, trial.total_cycles, trial.price) == ("DAY", 10, 1, 0)
    assert (intro.total_cycles, str(intro.price), regular.total_cycles, str(regular.price)) == (3, "24.99", 0, "49.99")


def test_shop_headline_says_ten_days(client: TestClient) -> None:
    page = client.get("/shop/penwright").text
    assert "Start your 10-day free trial — $0 today" in page
    assert "at least 3 days before the next billing date" in page and "first charge on day 11" in page


# ---- draft validation + template ----------------------------------------------------------------------------------
def test_template_draft_is_valid_and_short() -> None:
    draft = template_draft(CTX)
    assert validate_draft(draft, CTX) == []
    assert f'"{CLAUSE}"' in draft.body and len(draft.body.split()) < 120


@pytest.mark.parametrize(("change", "problem"), [
    (lambda b: b.replace(CLAUSE, "You must email them 3 days before billing."), "not quoted verbatim"),
    (lambda b: b.replace("I-ABC123", "your subscription"), "missing PayPal subscription ID"),
    (lambda b: b.replace("priya@subguard-demo.example", "my email"), "missing account email"),
    (lambda b: b.replace("10 November 2026", "today"), "missing date"),
    (lambda b: b.replace("confirm the cancellation in writing", "stop billing"), "confirm in writing"),
    (lambda b: b + " word" * 80, "must be under 120"),
    (lambda b: b + "\nSee https://penwright.example/offer", "contains a link"),
])
def test_validation_rejects_bad_drafts(change: Any, problem: str) -> None:
    good = template_draft(CTX)
    bad = EmailDraft(subject=good.subject, body=change(good.body))
    assert any(problem in p for p in validate_draft(bad, CTX)), validate_draft(bad, CTX)


@pytest.mark.parametrize("kind", ["anthropic", "openai", "mock"])
def test_draft_contract(kind: str) -> None:
    """Every provider returns a draft that passes the code checks (fakes return a good draft for the real SDKs)."""
    good = json.dumps(template_draft(CTX).model_dump())
    chat = {"anthropic": a_msg([{"type": "text", "text": good}]), "openai": o_msg({"content": good})}.get(kind)
    provider, fake = make(kind, chat=chat)
    draft = asyncio.run(provider.draft_cancellation_notice(CTX))
    assert validate_draft(draft, CTX) == []
    if fake is not None:
        sent = json.dumps((fake.messages if kind == "anthropic" else fake.completions).calls[0])
        assert CLAUSE in sent and "untrusted" in sent.lower()


class BrokenLLM:
    name, model = "anthropic", "test-model"

    def __init__(self, draft: EmailDraft | None = None) -> None:
        self.draft = draft

    async def draft_cancellation_notice(self, ctx: NoticeContext) -> EmailDraft:
        if self.draft is None:
            raise LLMError("Anthropic API unreachable")
        return self.draft


@pytest.mark.parametrize(("llm", "problem"), [
    (BrokenLLM(), "LLM error"),
    (BrokenLLM(EmailDraft(subject="Hi", body="Please cancel. Also we agree to pay a $50 fee. Thanks")), "missing"),
])
def test_template_fallback(demo_client: TestClient, llm: BrokenLLM, problem: str) -> None:
    c = demo_client
    svc_of(c).llm = llm  # type: ignore[assignment]
    _, notice = cancel_on_day5(c)
    assert notice["draft_source"] == "template" and notice["drafted_by"] == "standard template"
    assert any(problem in p for p in notice["draft_problems"])
    assert "$50" not in notice["body"] and "at least 3 days before the next billing date" in notice["body"]
    (row,) = audit(c, "cancellation_email_drafted")
    assert row["result"] == "template" and row["details"]["drafted_by"] == "standard template"


# ---- order + consent --------------------------------------------------------------------------------------------
def test_paypal_cancel_happens_before_the_email(demo_client: TestClient) -> None:
    c = demo_client
    main, notice = cancel_on_day5(c)
    assert sub(c, main["id"])["status"] == "CANCELLED"
    rows = [r for r in audit(c) if r.get("subscription_id") == main["id"]]
    events = [r["event"] for r in rows]
    assert events.index("paypal_cancel") < events.index("cancellation_email_drafted")
    assert notice["status"] == "draft" and not outbox_emails(c)  # drafted, not sent


def test_auto_cancel_drafts_but_never_sends(demo_client: TestClient) -> None:
    c = demo_client
    main = subscribe(c)
    advance_to(c, 11)  # no answer: Day 6 timer cancels, then nobody clicks anything
    assert sub(c, main["id"])["cancelled_by"] == "timer"
    (notice,) = c.get("/api/notices?user=priya").json()
    assert notice["status"] == "draft" and notice["by_timer"] and notice["sent_via"] is None
    assert not outbox_emails(c) and not audit(c, "cancellation_email_sent")
    (done,) = alerts(c, kind="cancelled")
    assert "Your cancellation email is ready to review and send." in done["body"]
    res = c.post(f"/api/alerts/{done['id']}/act", json={"user_id": "priya", "action": "review_email"}).json()
    assert res == {"notice_id": notice["id"]}


# ---- Send (demo) ------------------------------------------------------------------------------------------------
def test_send_saves_final_text_and_is_idempotent(demo_client: TestClient) -> None:
    c = demo_client
    _, notice = cancel_on_day5(c)
    edited_body = notice["body"] + "\n\nPS: Thanks for the trial."
    first = post_email(c, notice, body=edited_body)
    assert first.status_code == 200
    out = first.json()
    sent = out["notice"]
    assert not out["already_sent"] and sent["status"] == "sent" and sent["sent_via"] == "demo_outbox"
    assert sent["edited"] is True and sent["body"] == edited_body
    assert sent["sha256"] == hashlib.sha256(edited_body.encode()).hexdigest()
    (mail,) = outbox_emails(c)
    assert mail["to"] == "cancel@penwright.example" and mail["body"] == edited_body and mail["edited"] is True
    assert mail["sha256"] == sent["sha256"] and mail["sent_via"] == "demo_outbox" and mail["sent_at"]

    again = post_email(c, notice, body="something else").json()  # second click
    assert again["already_sent"] and again["notice"]["body"] == edited_body
    assert len(outbox_emails(c)) == 1 and len(audit(c, "cancellation_email_sent")) == 1
    page = c.get(f"/subscriptions/{notice['subscription_id']}").text
    assert 'data-testid="cancellation-notice"' in page and "Email sent (demo)" in page


def test_unedited_send_records_edited_no(demo_client: TestClient) -> None:
    c = demo_client
    _, notice = cancel_on_day5(c)
    sent = post_email(c, notice).json()["notice"]
    assert sent["edited"] is False and sent["sha256"] == notice["sha256"]
    (row,) = audit(c, "cancellation_email_sent")
    assert row["details"]["edited"] is False and row["actor"] == "user"


@pytest.mark.parametrize("edit", [{"to": " "}, {"body": ""}, {"to": "not-an-email"}])
def test_empty_to_or_body_is_rejected(demo_client: TestClient, edit: dict[str, str]) -> None:
    c = demo_client
    _, notice = cancel_on_day5(c)
    assert post_email(c, notice, **edit).status_code == 400
    assert not outbox_emails(c)


def test_only_the_owner_can_send(demo_client: TestClient) -> None:
    c = demo_client
    _, notice = cancel_on_day5(c)
    add_user(c)
    res = post_email(c, notice, user_id="intruder")
    assert res.status_code == 403 and res.json()["rule_id"] == "R5"
    assert not outbox_emails(c)


# ---- Open in Gmail ----------------------------------------------------------------------------------------------
def test_gmail_url_encoding() -> None:
    body = 'Hello & bye\nLine 2: "quoted" 100% #1 ?x=y'
    url = gmail_url("cancel@penwright.example", "Cancel I-1 & more", body)
    assert url.startswith("https://mail.google.com/mail/?view=cm&fs=1&to=")
    assert "\n" not in url and " " not in url and "%0A" in url and "%26" in url and "%23" in url
    q = parse_qs(urlsplit(url).query)
    assert q["to"] == ["cancel@penwright.example"] and q["su"] == ["Cancel I-1 & more"] and q["body"] == [body]


def test_open_in_gmail_uses_the_edited_text(demo_client: TestClient) -> None:
    c = demo_client
    _, notice = cancel_on_day5(c)
    res = post_email(c, notice, "gmail", subject="My edited subject").json()
    assert res["notice"]["sent_via"] == "gmail_compose_link" and res["notice"]["edited"] is True
    assert parse_qs(urlsplit(res["url"]).query)["su"] == ["My edited subject"]
    assert audit(c, "cancellation_email_gmail_opened") and outbox_emails(c)[0]["sent_via"] == "gmail_compose_link"


def test_gmail_link_too_long(demo_client: TestClient) -> None:
    c = demo_client
    _, notice = cancel_on_day5(c)
    res = post_email(c, notice, "gmail", body="x " * GMAIL_MAX_URL).json()
    assert res["too_long"] and res["url"] is None and res["notice"]["status"] == "draft"
    assert not outbox_emails(c)
