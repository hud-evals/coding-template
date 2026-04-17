"""Task definitions for coding environment.

Each task is created via scenario.task() and can be run locally or remotely:

    hud eval . --task-ids sample-json-bug
    hud eval . --all
    hud sync tasks . farrel-coding-tasks
"""

from env import env, make_prompt, setup_task
from grading import AgentPatchGrader, Grade, ValidateMode

# =============================================================================
# Basic — single-file bugs with straightforward fixes
# =============================================================================


@env.scenario("sample-json-bug", exclude_tools=["hud_validate"])
async def sample_json_bug(hints_enabled: bool = False, validate_mode: ValidateMode | None = None):
    """Fix the JSON serialization bug in server.py."""

    setup_task(
        task_id="sample_json_bug",
        base="server_fix_baseline",
        test="server_fix_test",
        golden="server_fix_golden",
        validate_mode=validate_mode,
    )

    description = """Fix the JSON serialization bug in server.py.

The API server's responses are malformed. When you make a request to any endpoint,
the response body is not valid JSON - it looks like a Python dict representation
instead of proper JSON (e.g., single quotes instead of double quotes)."""

    if hints_enabled:
        description += "\n\nHint: Look at how the response body is constructed from the data dict."

    prompt = make_prompt(description)
    _ = yield prompt

    grade = Grade.from_subscores([
        AgentPatchGrader.grade(
            weight=1.0,
            problem_id="sample_json_bug",
            test_files=["test_server.py"],
            validate_mode=validate_mode,
        )
    ])
    yield grade.score


@env.scenario("sentry-fix", exclude_tools=["hud_validate"])
async def sentry_fix(hints_enabled: bool = False, validate_mode: ValidateMode | None = None):
    """Fix the KeyError crash on missing user profile data."""

    setup_task(
        task_id="sentry_fix",
        base="sentry_fix_baseline",
        test="sentry_fix_test",
        golden="sentry_fix_golden",
        validate_mode=validate_mode,
    )

    description = """Fix a crash in the user profile endpoint.

The user profile service crashes with a KeyError for certain users. Some users
have incomplete profile data — their profile field may be None or missing entirely.
The service works fine for users with complete profiles but fails for others.
Investigate and fix the error handling in the user service."""

    if hints_enabled:
        description += "\n\nHint: Check how user profiles with missing or null nested data are accessed."

    prompt = make_prompt(description)
    _ = yield prompt

    grade = Grade.from_subscores([
        AgentPatchGrader.grade(
            weight=1.0,
            problem_id="sentry_fix",
            test_files=["test_user_service.py"],
            validate_mode=validate_mode,
        )
    ])
    yield grade.score


@env.scenario("settings-bug", exclude_tools=["hud_validate"])
async def settings_bug(hints_enabled: bool = False, validate_mode: ValidateMode | None = None):
    """Fix the settings merge logic that drops falsy values."""

    setup_task(
        task_id="settings_bug",
        base="settings_bug_baseline",
        test="settings_bug_test",
        golden="settings_bug_golden",
        validate_mode=validate_mode,
    )

    description = """Fix a bug in the user settings system.

Users report that setting preferences to values like false, 0, or empty string
causes those settings to revert to their defaults instead of being saved. For
example, setting "dark_mode" to false or "volume" to 0 doesn't stick — the
settings page always shows the default values instead. Investigate the settings
merge logic and fix the issue."""

    if hints_enabled:
        description += (
            "\n\nHint: Look at how the settings service filters values when"
            " merging custom settings with defaults."
        )

    prompt = make_prompt(description)
    _ = yield prompt

    grade = Grade.from_subscores([
        AgentPatchGrader.grade(
            weight=1.0,
            problem_id="settings_bug",
            test_files=["test_settings.py"],
            validate_mode=validate_mode,
        )
    ])
    yield grade.score


# =============================================================================
# Medium — multi-file bugs requiring system understanding
# =============================================================================


@env.scenario("notif-bug", exclude_tools=["hud_validate"])
async def notif_bug(hints_enabled: bool = False, validate_mode: ValidateMode | None = None):
    """Fix the event routing bug that silences all notifications."""

    setup_task(
        task_id="notif_bug",
        base="notif_bug_baseline",
        test="notif_bug_test",
        golden="notif_bug_golden",
        validate_mode=validate_mode,
    )

    description = """Fix the broken notification system.

The notification system is completely silent — no notifications are generated when
tasks are created, assigned, or completed. The event handlers are registered and
the notification service is initialized, but events never reach their handlers.
Investigate the event routing pipeline and fix the issue."""

    if hints_enabled:
        description += (
            "\n\nHint: Compare the event type format used when events are"
            " emitted vs when handlers are registered."
        )

    prompt = make_prompt(description)
    _ = yield prompt

    grade = Grade.from_subscores([
        AgentPatchGrader.grade(
            weight=1.0,
            problem_id="notif_bug",
            test_files=["test_notifications.py"],
            validate_mode=validate_mode,
        )
    ])
    yield grade.score


@env.scenario("order-bug", exclude_tools=["hud_validate"])
async def order_bug(hints_enabled: bool = False, validate_mode: ValidateMode | None = None):
    """Fix the tax/discount calculation order bug."""

    setup_task(
        task_id="order_bug",
        base="order_bug_baseline",
        test="order_bug_test",
        golden="order_bug_golden",
        validate_mode=validate_mode,
    )

    description = """Fix the order pricing calculation.

Customers report being overcharged when using discount codes. The discount appears
in the receipt but the final total is higher than expected. For example, a $100
order with a 10% discount and 8% tax should total $97.20, but customers are being
charged more. Investigate the order processing pipeline and fix the pricing
calculation."""

    if hints_enabled:
        description += (
            "\n\nHint: Look at the order in which tax and discount are applied"
            " in the pricing service."
        )

    prompt = make_prompt(description)
    _ = yield prompt

    grade = Grade.from_subscores([
        AgentPatchGrader.grade(
            weight=1.0,
            problem_id="order_bug",
            test_files=["test_order_pricing.py"],
            validate_mode=validate_mode,
        )
    ])
    yield grade.score


# =============================================================================
# Hard — subtle bugs in complex, multi-file systems
# =============================================================================


@env.scenario("settings-v2", exclude_tools=["hud_validate"])
async def settings_v2(hints_enabled: bool = False, validate_mode: ValidateMode | None = None):
    """Fix the CompactDict class that drops falsy values during iteration."""

    setup_task(
        task_id="settings_v2",
        base="settings_v2_baseline",
        test="settings_v2_test",
        golden="settings_v2_golden",
        validate_mode=validate_mode,
    )

    description = """Fix disappearing fields in API responses.

API responses for the settings and user endpoints are randomly dropping fields
that have values like 0, false, or empty string. Direct key lookups work fine,
but when responses are serialized to JSON, certain valid fields disappear. The
issue affects multiple endpoints and seems related to how data is iterated over
during serialization."""

    if hints_enabled:
        description += (
            "\n\nHint: Investigate the custom CompactDict class in utils/types.py"
            " — look at how it filters values during iteration."
        )

    prompt = make_prompt(description)
    _ = yield prompt

    grade = Grade.from_subscores([
        AgentPatchGrader.grade(
            weight=1.0,
            problem_id="settings_v2",
            test_files=["test_settings.py"],
            validate_mode=validate_mode,
        )
    ])
    yield grade.score


@env.scenario("webhook-bug", exclude_tools=["hud_validate"])
async def webhook_bug(hints_enabled: bool = False, validate_mode: ValidateMode | None = None):
    """Fix the shared list mutation bug in notification builder."""

    setup_task(
        task_id="webhook_bug",
        base="webhook_bug_baseline",
        test="webhook_bug_test",
        golden="webhook_bug_golden",
        validate_mode=validate_mode,
    )

    description = """Fix inconsistent webhook notification channels.

Webhook notifications work correctly on the first request for a given event type,
but subsequent requests for the same event type produce incorrect or duplicated
notification channels. The issue gets worse with repeated requests — channels
accumulate and sort order changes unexpectedly."""

    if hints_enabled:
        description += (
            "\n\nHint: Look for shared mutable state in the notification builder"
            " — specifically how channel lists are handled between calls."
        )

    prompt = make_prompt(description)
    _ = yield prompt

    grade = Grade.from_subscores([
        AgentPatchGrader.grade(
            weight=1.0,
            problem_id="webhook_bug",
            test_files=["test_notifications.py"],
            validate_mode=validate_mode,
        )
    ])
    yield grade.score


# =============================================================================
# Task registry — discovered by `hud sync tasks .`
# =============================================================================

# Basic
json_bug_task = sample_json_bug.task()
json_bug_task.slug = "sample-json-bug"

sentry_fix_task = sentry_fix.task()
sentry_fix_task.slug = "sentry-fix"

settings_bug_task = settings_bug.task()
settings_bug_task.slug = "settings-bug"

settings_bug_hints_task = settings_bug.task(hints_enabled=True)
settings_bug_hints_task.slug = "settings-bug-hints"

# Medium
notif_bug_task = notif_bug.task()
notif_bug_task.slug = "notif-bug"

order_bug_task = order_bug.task()
order_bug_task.slug = "order-bug"

order_bug_hints_task = order_bug.task(hints_enabled=True)
order_bug_hints_task.slug = "order-bug-hints"

# Hard
settings_v2_task = settings_v2.task()
settings_v2_task.slug = "settings-v2"

webhook_bug_task = webhook_bug.task()
webhook_bug_task.slug = "webhook-bug"

tasks = {
    # Basic
    "sample_json_bug": json_bug_task,
    "sentry_fix": sentry_fix_task,
    "settings_bug": settings_bug_task,
    "settings_bug_hints": settings_bug_hints_task,
    # Medium
    "notif_bug": notif_bug_task,
    "order_bug": order_bug_task,
    "order_bug_hints": order_bug_hints_task,
    # Hard
    "settings_v2": settings_v2_task,
    "webhook_bug": webhook_bug_task,
}
