# Corner cases (spec section 8): where each one is handled and tested

Every case has code and at least one test, or a doc note where the spec allows one ("doc").
Test names are `file::test`. `tests/test_scenario.py` also runs the demo story (userA + Penwright) end to end.
Cases 35 and 36 belonged to the price-rise flow, which was removed when the story was simplified (D-090).

## PayPal and subscription lifecycle

| # | Case | Code | Tests |
|---|---|---|---|
| 1 | Popup closed / never approved: no timer, no snapshot, expire after 3 h | `routes/subscriptions.py` register | `test_checkout::test_unapproved_subscription_is_not_registered` + **doc note** below |
| 2 | onApprove but PayPal still `APPROVAL_PENDING`/`APPROVED`: poll up to 60 s | `routes/subscriptions.py` `_wait_active` | `test_corner_cases::test_register_polls_until_active`, `test_corner_cases::test_register_gives_up_if_never_active` |
| 3 | Cancelling an already-cancelled subscription (422) counts as success | `integrations/paypal_gateway.py` | `test_paypal_gateway::test_cancel_already_cancelled_is_success`, `test_paypal_gateway::test_422_from_paypal_then_cancelled_counts_as_success`, `test_paypal_rest::test_422_maps_to_status_invalid` |
| 4 | Cancel fails: refresh on 401, retry with the same request id, then FAILED + Layer 2 + urgent alert | `paypal_gateway.py`, `paypal_rest.py`, `core/timers.py` | `test_paypal_gateway::test_retries_reuse_the_same_request_id`, `test_paypal_gateway::test_401_retried_once`, `test_paypal_gateway::test_gives_up_and_releases_claim`, `test_paypal_rest::test_401_refreshes_token_and_resends_same_request_id`, `test_policy::test_cancel_failure_switches_to_layer2` |
| 5 | Merchant suspends / subscription expires: show it, cancel pending timers | `core/escalation.py` `apply_status` | `test_policy::test_paypal_side_suspend_cancels_timer`, `test_corner_cases::test_webhook_dedupe_by_event_id_and_status_transition` |
| 6 | Duplicate webhooks, webhook + poller on the same change | `routes/webhooks.py`, `escalation.apply_status` | `test_corner_cases::test_webhook_dedupe_by_event_id_and_status_transition`, `test_corner_cases::test_webhook_then_poller_sees_the_same_change_once`, `test_corner_cases::test_webhook_signature_required_in_sandbox` |
| 7 | PayPal MCP down or tool renamed: SDK fallback + warning in healthz | `integrations/paypal_mcp.py`, `paypal_gateway.py` | `test_paypal_gateway::test_mcp_down_falls_back_to_sdk_with_warning` |
| 8 | Non-USD plans: format with the plan's currency, never mix currencies in a KPI | `pricing.money(amount, currency)`, `savings.protected_by_currency`, `/api/kpis` | `test_corner_cases::test_currencies_never_mixed_in_kpi`, `test_corner_cases::test_kpi_reports_other_currencies_separately` + **doc note** below |
| 9 | Sandbox mode with a non-sandbox base URL refuses to start | `config.validate_settings` | `test_config::test_sandbox_refuses_non_sandbox_base_url` |

## Timers, deadlines, the clock

| # | Case | Code | Tests |
|---|---|---|---|
| 10 | Keep at the same moment the timer fires | `core/timers.py` `_claim` under the store lock | `test_policy::test_keep_vs_timer_race_is_consistent` |
| 11 | Keep after the timer fired: explain it's already cancelled (no Restart trial, D-112) | `timers.keep` | `test_story::test_no_answer_auto_cancels_on_day6` (`too_late`) |
| 12 | Warning failed on every channel: no auto-cancel, retry, urgent alert at the deadline | `notify.warning_basis`, `policy._timer_decision`, `timers.fire` | `test_policy::test_failed_warnings_block_auto_cancel` |
| 13 | Trial/notice too short to warn 24 h ahead: manual decision | `risk.compute_deadlines`, `timers.create_trial_timer` | `test_policy::test_short_trial_needs_a_manual_decision`, `test_auditor::test_short_trial_gets_no_auto_timer` |
| 14 | Jumping several days: each day in order, no duplicate alerts | `clock.advance`, alert idempotency keys | `test_story::test_jump_is_idempotent` |
| 15 | Demo reset: idempotent, keeps `sandbox_ids.json`, archives the audit log | `store.reset`, `/api/demo/reset` | `test_store::test_reset_keeps_sandbox_ids_and_archives_audit_log`, `test_pages::test_demo_reset` |
| 16 | Times in UTC; sim days are integers | `store.utcnow`, models | `test_corner_cases::test_times_are_utc_and_days_are_ints` |

## Storage

| # | Case | Code | Tests |
|---|---|---|---|
| 17 | Corrupt or missing JSON file: recover, never crash | `store.load` | `test_store::test_corrupt_file_recovered`, `test_store::test_corrupt_users_file_reseeds`, `test_store::test_missing_files_created_from_defaults_and_seeds` |
| 18 | Crash mid-write: the old file stays intact | `store.atomic_write_text` | `test_store::test_atomic_write_crash_before_replace_keeps_old_file` |
| 19 | Audit log append-only; a broken chain is reported (API + UI) | `core/audit_log.py`, `grids.js` chain badge | `test_audit_log::test_tampered_entry_detected`, `test_audit_log::test_deleted_entry_detected`, `test_audit_log::test_garbage_line_detected` |

## AI and fine-print review

| # | Case | Code | Tests |
|---|---|---|---|
| 20 | Hidden prompt injection: ignored, flagged, score unchanged (both providers) | `core/patterns.py`, `core/auditor.py`, `risk.py` | `test_auditor::test_injection_never_changes_the_score`, `test_llm_providers::test_model_that_obeys_injection_is_overruled`, `test_llm_providers::test_review_contract` |
| 21 | Hallucinated quotes: verbatim check, drop, retry once | `core/auditor.py` | `test_auditor::test_hallucinated_quote_dropped_and_retried_once`, `test_auditor::test_hallucination_twice_keeps_only_verified` |
| 22 | LLM down / slow / invalid JSON: retry, then labelled rule-based fallback | `core/auditor.py`, `core/agent.py` | `test_auditor::test_llm_down_uses_labelled_rule_fallback`, `test_auditor::test_invalid_json_then_valid_is_retried`, `test_auditor::test_slow_llm_times_out_to_fallback`, `test_chat::test_llm_down_is_explained` |
| 23 | Provider differences hidden behind `llm/base.py` | `llm/*_provider.py` | `test_llm_providers::test_review_contract`, `test_llm_providers::test_chat_step_contract`, `test_llm_providers::test_anthropic_request_shape`, `test_llm_providers::test_openai_request_shape` |
| 24 | Unknown `LLM_PROVIDER` / missing key: clear startup error | `config.validate_settings` | `test_config::test_unknown_llm_provider`, `test_config::test_sandbox_missing_key_names_variable_and_suggests_mock`, `test_config::test_sandbox_openai_requires_openai_vars` |
| 25 | Page price differs from PayPal: `TERMS_MISMATCH`, PayPal wins | `core/crosscheck.py` | `test_auditor::test_price_on_paypal_differs_from_page_is_mismatch` |
| 26 | Text only inside an image | `integrations/capture_live.py` sends the screenshot to the vision model | **doc note** below |
| 27 | "Trial ends after 3 exports": flag it; too many exports -> warn + move the deadline | `escalation.early_trial_end`, shop `POST /shop/<m>/app/export` | `test_corner_cases::test_too_many_exports_warns_and_moves_deadline`, `test_auditor::test_penwright_review_matches_spec` |
| 28 | Honest terms: low score, `CLEAR_TERMS`, no auto-timer (no free trial) | `risk.py`, `timers.on_registered` (timer only for a free trial) | `test_auditor::test_honest_terms_score_low` (no honest merchant in the demo since D-090) |

## Agent and policy

| # | Case | Code | Tests |
|---|---|---|---|
| 29 | LLM tries to cancel directly / too many subscriptions | `policy.py`, `chat_tools.run_tool` | `test_policy::test_r1_cancel_needs_a_confirmation_tap`, `test_policy::test_r4_max_ten_per_command`, `test_chat::test_model_cannot_cancel_directly`, `test_chat::test_too_many_in_one_command_blocked` |
| 30 | Expired, reused or mismatched token | `policy._consume` | `test_policy::test_r3_expired_reused_mismatched_and_foreign_tokens`, `test_scenario::test_story_end_to_end_with_chat` (reuse) |
| 31 | Another user's subscription (a test-only second user vs userA) | `policy._precheck`, `chat_tools._own`, subscription page | `test_policy::test_r5_another_user_cannot_touch_useras_subscriptions`, `test_chat::test_model_cannot_touch_other_users_subscription`, `test_pages::test_subscription_page` |
| 32 | `essential` is never auto-cancelled | `policy._timer_decision` | `test_policy::test_r6_essential_never_auto_cancelled_but_manual_ok` |
| 33 | Ambiguous cancel request: ask, don't act | `llm/mock_chat.py`, chat system prompt | `test_chat::test_ambiguous_cancel_asks_which_one` |
| 34 | Multi-cancel partial failure: per-item results | `actions.cancel_confirmed`, `chat.js` | `test_policy::test_r7_partial_failure_reports_per_item` |
| 35 | Price decrease / rise | **Removed** with the price-rise flow (D-090). The R2 rule itself is unchanged in `policy.py` | `test_policy::test_r2_price_rise_allowed_with_setting` (policy only) |
| 36 | Keep at a new price | **Removed** with the price-rise flow (D-090). Plain Keep: `timers.keep` | `test_story::test_keep_on_day5_means_no_more_prompts` |

## Notifications and evidence

| # | Case | Code | Tests |
|---|---|---|---|
| 37 | Zapier down: retry with backoff, then failed (feeds R2); in-app still works | `integrations/notify.py` | `test_corner_cases::test_zapier_retries_then_fails`, `test_corner_cases::test_zapier_accepts_after_a_retry`, `test_policy::test_failed_warnings_block_auto_cancel` |
| 38 | Cancellation email: drafted after the PayPal cancel, never sent without a click; final text stored with SHA-256, recipient, time, edited, sent_via; idempotent Send; empty To/Body rejected; Gmail link too long | `core/notices.py`, `routes/notices.py`, `static/email.js` | `test_notices.py`, `test_story::test_cancel_on_day5`, `test_story::test_no_answer_auto_cancels_on_day6` |
| 39 | Secrets never in logs or the audit log | `audit_log.mask_secrets`, `main.JsonFormatter` | `test_audit_log::test_secrets_and_emails_masked` |

## Doc notes

- **1. Unapproved subscriptions.** SubGuard only stores a subscription after PayPal confirms it `ACTIVE`, so an
  abandoned approval never enters our list: there's no timer, no snapshot, and nothing for us to expire. The
  `APPROVAL_PENDING` subscription exists only on PayPal's side, and PayPal expires it on its own (D-070).
- **8. Currencies.** All demo plans are USD (`DEMO_CURRENCY`). Amounts show in each plan's currency, and the
  Money protected KPI only adds amounts in the demo currency; other currencies appear next to it, labelled
  (for example "$524.88/yr + €60/yr"). A confirmation card that mixes currencies isn't supported in v1:
  its total assumes one currency.
- **26. Text only inside an image.** In sandbox mode, live Playwright sends a full-page screenshot to the vision
  model with the extracted text, so text drawn in an image can still be read. The verbatim-quote check only
  accepts quotes found in the captured *text*, though, so a clause that exists only as pixels is dropped and not
  reported. That's a known v1 limitation; OCR on the screenshot would fix it. Mock mode uses static HTML capture
  (no screenshot).
