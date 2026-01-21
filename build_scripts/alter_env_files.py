import os
import shutil


def upsert_env_variables(file_path: str, updates: dict[str, str]) -> None:
    """Update or insert environment variables in a file."""
    try:
        with open(file_path) as env_file:
            original_lines = env_file.read().splitlines()
    except FileNotFoundError:
        original_lines = []

    replaced_keys = set()
    new_lines = []

    for line in original_lines:
        updated = False
        for key, value in updates.items():
            if line.startswith(f"{key}="):
                new_lines.append(f"{key}={value}")
                replaced_keys.add(key)
                updated = True
                break
        if not updated:
            new_lines.append(line)

    for key, value in updates.items():
        if key not in replaced_keys:
            new_lines.append(f"{key}={value}")

    with open(file_path, "w") as env_file:
        env_file.write("\n".join(new_lines) + "\n")


def main():
    """
    Configure environment files for your project.
    
    CUSTOMIZE THIS FUNCTION for your project's environment setup.
    
    Examples:
    
    === NODE.JS PROJECT ===
    upsert_env_variables(
        "/home/ubuntu/project/.env.test",
        {
            "DATABASE_URL": "postgresql://user:pass@localhost:5432/test_db",
            "NODE_ENV": "test",
        }
    )
    
    === PYTHON DJANGO PROJECT ===
    upsert_env_variables(
        "/home/ubuntu/project/.env",
        {
            "DATABASE_URL": "postgresql://user:pass@localhost:5432/test_db",
            "DJANGO_SETTINGS_MODULE": "project.settings.test",
        }
    )
    
    === JAVA SPRING PROJECT ===
    Create application-test.properties or application-test.yml
    
    === ANY PROJECT ===
    - Set database URLs
    - Set test environment flags
    - Set API keys or secrets (use secure values for testing)
    """
    
    project_dir = os.environ.get("PROJECT_DIR", f"/home/ubuntu/{os.environ.get('FOLDER_NAME')}")
    
    # [CUSTOMIZE] Configure your environment files here
    # Example:
    # upsert_env_variables(
    #     f"{project_dir}/.env.test",
    #     {
    #         "DATABASE_URL": "[TEST_DATABASE_URL]",
    #         "API_KEY": "[TEST_API_KEY]",
    #     }
    # )
    
    pass  # Remove this when implementing


if __name__ == "__main__":
    main()
