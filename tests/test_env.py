"""In-process wiring smoke tests (no Docker): the served surface is well-formed."""

import json
from pathlib import Path

from env import env

FIXTURE_INSTANCE = json.loads((Path(__file__).parent / "fixtures" / "instance" / "instance.json").read_text("utf-8"))


def test_env_identity():
    assert env.name == "swe-task-example"


def test_generic_template_registered():
    assert "coding-task" in env.tasks
    assert env.tasks["coding-task"].manifest_entry()["id"] == "coding-task"


def test_coding_task_prompt_is_hinted_and_existing_arg_names_stay():
    """Toptal rows still pass ``description``; the console gets a text box."""
    properties = env.tasks["coding-task"].manifest_entry()["args"]["properties"]
    assert properties["description"]["x-hud-hint"] == "prompt"
    assert "hud_api_key" in properties
    assert "description" in env.tasks["coding-task"].manifest_entry()["args"]["required"]


def test_swe_task_arguments_are_uploads_plus_prompt():
    """The MC model: a prompt text box and file pickers; the key hidden; nothing else."""
    args_schema = env.tasks["swe-task"].manifest_entry()["args"]
    properties = args_schema["properties"]
    assert set(properties) == {
        "prompt",
        "codebase",
        "grading",
        "golden_solution",
        "llm_rubric",
        "hud_api_key",
        "validate_mode",
    }
    assert properties["prompt"]["x-hud-hint"] == "prompt"
    for upload in ("codebase", "grading", "golden_solution", "llm_rubric"):
        # The hint sits on the property itself so optional uploads get the picker too.
        assert properties[upload]["x-hud-hint"] == "data-files", upload
    # The picker hands over a list; exactly one file per argument.
    assert properties["codebase"]["type"] == "array" and properties["codebase"]["maxItems"] == 1
    assert properties["codebase"]["items"]["$ref"] == "#/$defs/DataFileRef"
    required = set(args_schema.get("required") or [])
    assert required == {"prompt", "codebase", "grading"}
    assert "file_id" in args_schema["$defs"]["DataFileRef"]["properties"]
    # No repo url, sha or setup command: those live in the uploads.
    assert not {"repo_url", "base_sha", "setup_command", "services"} & set(properties)


def test_swe_bench_template_registered_when_instance_baked():
    """conftest points INSTANCE_DIR at the fixture instance, as an instance image would."""
    instance_id = FIXTURE_INSTANCE["instance_id"]
    assert instance_id in env.tasks
    assert env.tasks[instance_id].manifest_entry()["id"] == instance_id
