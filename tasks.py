"""Task definitions for the coding environment (HUD v6).

The generic ``coding_bug`` template (defined in ``env.py``) accepts all task
content as parameters (description, test files). Each call mints a distinct
``Task`` by passing different values — no new template function needed.

Branch names are derived from ``task_id`` by convention:
``{task_id}_baseline``, ``{task_id}_test``, ``{task_id}_golden``.

    hud eval tasks.py claude --task-ids sentry-fix
    hud eval tasks.py claude --full
    hud sync tasks coding-tasks

``env`` is re-exported so ``hud eval tasks.py`` (which serves this source on a
local substrate) can find the Environment; the public ``tasks`` list is what
``hud eval`` / ``hud sync`` collect.
"""

from env import coding_bug, env  # noqa: F401  (env re-exported for `hud eval tasks.py`)


# =============================================================================
# Four hand-picked bugs: a KeyError, broken event routing, and two subtle
# falsy-value / shared-state bugs in multi-file systems. Span Basic -> Hard.
# =============================================================================

_sentry_fix = coding_bug(
    task_id="sentry_fix",
    description=(
        "Fix a crash in the user profile endpoint.\n\n"
        "The user profile service crashes with a KeyError for certain users. Some users\n"
        "have incomplete profile data — their `profile` field may be None or missing\n"
        "entirely. The service works fine for users with complete profiles but fails for\n"
        "others. Investigate and fix the error handling in the user service.\n\n"
        "Expected behavior when a user has no profile (the `profile` field is None or\n"
        "absent): fall back to the user's top-level `name` for the display name and use an\n"
        "empty string for the bio. Users with a complete profile keep their existing\n"
        "`display_name` and `bio`."
    ),
    test_files=["test_user_service.py"],
)
_sentry_fix.slug = "sentry-fix"

_notif_bug = coding_bug(
    task_id="notif_bug",
    description=(
        "Fix the broken notification system.\n\n"
        "The notification system is completely silent — no notifications are generated when\n"
        "tasks are created, assigned, or completed. The event handlers are registered and\n"
        "the notification service is initialized, but events never reach their handlers.\n"
        "Investigate the event routing pipeline and fix the issue."
    ),
    test_files=["test_notifications.py"],
)
_notif_bug.slug = "notif-bug"

_settings_v2 = coding_bug(
    task_id="settings_v2",
    description=(
        "Fix disappearing fields in API responses.\n\n"
        "API responses for the settings and user endpoints are randomly dropping fields\n"
        "that have values like 0, false, or empty string. Direct key lookups work fine,\n"
        "but when responses are serialized to JSON, certain valid fields disappear. The\n"
        "issue affects multiple endpoints and seems related to how data is iterated over\n"
        "during serialization."
    ),
    test_files=["test_settings.py"],
)
_settings_v2.slug = "settings-v2"

_webhook_bug = coding_bug(
    task_id="webhook_bug",
    description=(
        "Fix inconsistent webhook notification channels.\n\n"
        "Webhook notifications work correctly on the first request for a given event type,\n"
        "but subsequent requests for the same event type produce incorrect or duplicated\n"
        "notification channels. The issue gets worse with repeated requests — channels\n"
        "accumulate and sort order changes unexpectedly."
    ),
    test_files=["test_notifications.py"],
)
_webhook_bug.slug = "webhook-bug"


# =============================================================================
# Task registry — collected by ``hud eval`` / ``hud sync tasks``
# =============================================================================

tasks = [
    _sentry_fix,
    _notif_bug,
    _settings_v2,
    _webhook_bug,
]
