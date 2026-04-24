"""Task definitions for coding environment.

One generic ``coding_bug`` scenario accepts all task content as parameters
(description, test files). Each ``.task()`` call produces a distinct task by
passing different values — no new scenario function needed.

Branch names are derived from ``task_id`` by convention:
``{task_id}_baseline``, ``{task_id}_test``, ``{task_id}_golden``.

    hud eval . --task-ids sample-json-bug
    hud eval . --all
    hud sync tasks . coding-tasks
"""

from env import env, make_prompt, setup_task
from grading import AgentPatchGrader, Grade, ValidateMode


# =============================================================================
# Scenario — generic bug-fix template
# =============================================================================


@env.scenario("coding-bug", exclude_tools=["hud_validate"])
async def coding_bug(
    task_id: str,
    description: str,
    test_files: list[str],
    validate_mode: ValidateMode | None = None,
):
    """Fix a bug in the codebase.

    Branch names are derived from *task_id* by convention:
    ``{task_id}_baseline``, ``{task_id}_test``, ``{task_id}_golden``.

    Args:
        task_id: Unique identifier (e.g. "sample_json_bug").
        description: Task description shown to the agent.
        test_files: List of test file paths applied via patch.
        validate_mode: "baseline_fail" or "golden_pass" for validation.
    """
    setup_task(
        task_id=task_id,
        validate_mode=validate_mode,
    )

    prompt = make_prompt(description)
    _ = yield prompt

    grade = Grade.from_subscores(
        [
            AgentPatchGrader.grade(
                weight=1.0,
                problem_id=task_id,
                test_files=test_files,
                validate_mode=validate_mode,
            )
        ]
    )
    yield grade.score


# =============================================================================
# Tasks — Basic (single-file bugs with straightforward fixes)
# =============================================================================

_sample_json_bug = coding_bug.task(
    task_id="sample_json_bug",
    description=(
        "Fix the JSON serialization bug in server.py.\n\n"
        "The API server's responses are malformed. When you make a request to any endpoint,\n"
        "the response body is not valid JSON - it looks like a Python dict representation\n"
        "instead of proper JSON (e.g., single quotes instead of double quotes)."
    ),
    test_files=["test_server.py"],
)
_sample_json_bug.slug = "sample-json-bug"

_sentry_fix = coding_bug.task(
    task_id="sentry_fix",
    description=(
        "Fix a crash in the user profile endpoint.\n\n"
        "The user profile service crashes with a KeyError for certain users. Some users\n"
        "have incomplete profile data \u2014 their profile field may be None or missing entirely.\n"
        "The service works fine for users with complete profiles but fails for others.\n"
        "Investigate and fix the error handling in the user service."
    ),
    test_files=["test_user_service.py"],
)
_sentry_fix.slug = "sentry-fix"

_settings_bug = coding_bug.task(
    task_id="settings_bug",
    description=(
        "Fix a bug in the user settings system.\n\n"
        "Users report that setting preferences to values like false, 0, or empty string\n"
        "causes those settings to revert to their defaults instead of being saved. For\n"
        'example, setting "dark_mode" to false or "volume" to 0 doesn\'t stick \u2014 the\n'
        "settings page always shows the default values instead. Investigate the settings\n"
        "merge logic and fix the issue."
    ),
    test_files=["test_settings.py"],
)
_settings_bug.slug = "settings-bug"

_settings_bug_hints = coding_bug.task(
    task_id="settings_bug",
    description=(
        "Fix a bug in the user settings system.\n\n"
        "Users report that setting preferences to values like false, 0, or empty string\n"
        "causes those settings to revert to their defaults instead of being saved. For\n"
        'example, setting "dark_mode" to false or "volume" to 0 doesn\'t stick \u2014 the\n'
        "settings page always shows the default values instead. Investigate the settings\n"
        "merge logic and fix the issue.\n\n"
        "Hint: Look at how the settings service filters values when"
        " merging custom settings with defaults."
    ),
    test_files=["test_settings.py"],
)
_settings_bug_hints.slug = "settings-bug-hints"

# =============================================================================
# Tasks — Medium (multi-file bugs requiring system understanding)
# =============================================================================

_notif_bug = coding_bug.task(
    task_id="notif_bug",
    description=(
        "Fix the broken notification system.\n\n"
        "The notification system is completely silent \u2014 no notifications are generated when\n"
        "tasks are created, assigned, or completed. The event handlers are registered and\n"
        "the notification service is initialized, but events never reach their handlers.\n"
        "Investigate the event routing pipeline and fix the issue."
    ),
    test_files=["test_notifications.py"],
)
_notif_bug.slug = "notif-bug"

_order_bug = coding_bug.task(
    task_id="order_bug",
    description=(
        "Fix the order pricing calculation.\n\n"
        "Customers report being overcharged when using discount codes. The discount appears\n"
        "in the receipt but the final total is higher than expected. For example, a $100\n"
        "order with a 10% discount and 8% tax should total $97.20, but customers are being\n"
        "charged more. Investigate the order processing pipeline and fix the pricing\n"
        "calculation."
    ),
    test_files=["test_order_pricing.py"],
)
_order_bug.slug = "order-bug"

_order_bug_hints = coding_bug.task(
    task_id="order_bug",
    description=(
        "Fix the order pricing calculation.\n\n"
        "Customers report being overcharged when using discount codes. The discount appears\n"
        "in the receipt but the final total is higher than expected. For example, a $100\n"
        "order with a 10% discount and 8% tax should total $97.20, but customers are being\n"
        "charged more. Investigate the order processing pipeline and fix the pricing\n"
        "calculation.\n\n"
        "Hint: Look at the order in which tax and discount are applied"
        " in the pricing service."
    ),
    test_files=["test_order_pricing.py"],
)
_order_bug_hints.slug = "order-bug-hints"

# =============================================================================
# Tasks — Hard (subtle bugs in complex, multi-file systems)
# =============================================================================

_settings_v2 = coding_bug.task(
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

_webhook_bug = coding_bug.task(
    task_id="webhook_bug",
    description=(
        "Fix inconsistent webhook notification channels.\n\n"
        "Webhook notifications work correctly on the first request for a given event type,\n"
        "but subsequent requests for the same event type produce incorrect or duplicated\n"
        "notification channels. The issue gets worse with repeated requests \u2014 channels\n"
        "accumulate and sort order changes unexpectedly."
    ),
    test_files=["test_notifications.py"],
)
_webhook_bug.slug = "webhook-bug"

# =============================================================================
# Task registry — discovered by ``hud sync tasks .``
# =============================================================================

tasks = {
    # Basic
    "sample_json_bug": _sample_json_bug,
    "sentry_fix": _sentry_fix,
    "settings_bug": _settings_bug,
    "settings_bug_hints": _settings_bug_hints,
    # Medium
    "notif_bug": _notif_bug,
    "order_bug": _order_bug,
    "order_bug_hints": _order_bug_hints,
    # Hard
    "settings_v2": _settings_v2,
    "webhook_bug": _webhook_bug,
}
