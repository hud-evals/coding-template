"""In-process wiring smoke tests for the v6 environment (no Docker required).

These don't serve the env or touch the target repo — they just confirm the
template is registered and the task rows are well-formed, so authoring mistakes
surface fast without a build.
"""

import stat

from env import env
from grading.runner import _remove_tree
from tasks import tasks


def test_template_registered():
    """The generic bug-fix template is registered under its public id."""
    assert "coding-bug" in env.tasks
    entry = env.tasks["coding-bug"].manifest_entry()
    assert entry["id"] == "coding-bug"


def test_env_identity():
    assert env.name == "coding"


def test_local_cleanup_removes_readonly_git_files(tmp_path):
    """Git for Windows marks packed objects read-only; local teardown must still be complete."""
    repo = tmp_path / "project"
    packed = repo / ".git" / "objects" / "pack" / "objects.pack"
    packed.parent.mkdir(parents=True)
    packed.write_bytes(b"pack")
    packed.chmod(stat.S_IREAD)

    _remove_tree(str(repo))

    assert not repo.exists()


def test_tasks_collected():
    """`hud eval` / `hud sync` collect the public ``tasks`` list."""
    assert len(tasks) == 4

    slugs = {t.slug for t in tasks}
    assert slugs == {"sentry-fix", "notif-bug", "settings-v2", "webhook-bug"}
    assert len(slugs) == len(tasks), "task slugs must be unique"

    for task in tasks:
        assert task.env == "coding"
        assert task.id == "coding-bug"
        assert "task_id" in task.args
        assert "test_files" in task.args
