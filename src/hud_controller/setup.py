import asyncio
import logging
import os
from pathlib import Path
from typing import Any

from .manual_dinit import ServiceLoader, SimpleDinit

logger = logging.getLogger(__name__)

TEST_MODE = os.environ.get("MCP_TESTING_MODE", "1") in ["1", "true"]

if TEST_MODE:
    # xfce starts quickly on our computer, but not in test
    XFCE_STARTUP_DELAY = 5
    CHROMIUM_STARTUP_DELAY = 3
else:
    # in test mode, we need to wait for the computer to start
    XFCE_STARTUP_DELAY = 30
    CHROMIUM_STARTUP_DELAY = 5


async def start_dinit():
    logger.info("Starting dinit")
    loader = ServiceLoader(Path("/etc/dinit.d"))
    services = loader.load_all()
    engine = SimpleDinit(services)
    engine.start("boot")


def setup_codebase(
    base: str,
    test: str,
    golden: str,
):
    """
    Setup the codebase for the given branch or commit.

    Args:
        base: The baseline branch/commit name to set up (preferred)
        test: Optional test branch/commit name to generate test.patch from
        golden: Optional golden branch/commit name to generate golden.patch from
    """

    # [CUSTOMIZE] Set your project directory
    project_dir = os.environ.get("PROJECT_DIR", "/home/ubuntu/[PROJECT_NAME]")
    os.chdir(project_dir)

    # [OPTIONAL] Remove problematic lines from Makefile (if applicable)
    # This example removes 'docker compose' lines that may cause issues
    makefile_path = Path(project_dir) / "Makefile"
    if makefile_path.is_file():
        # [CUSTOMIZE] Adjust the pattern to match lines you want to remove
        pattern_to_remove = "docker compose"  # Change as needed
        
        with open(makefile_path, encoding="utf-8") as f:
            original_lines = f.readlines()
            filtered_lines = [line for line in original_lines if pattern_to_remove not in line]
            if filtered_lines != original_lines:
                with open(makefile_path, "w", encoding="utf-8") as f:
                    f.writelines(filtered_lines)
                removed_count = len(original_lines) - len(filtered_lines)
                logger.info(f"Removed {removed_count} '{pattern_to_remove}' lines from Makefile")
            else:
                logger.info(f"No '{pattern_to_remove}' lines found in Makefile")
    else:
        logger.info(f"Makefile not found at {makefile_path}; skipping cleanup")


def start_dinit_script():
    """Entry point for the start_dinit script."""
    asyncio.run(start_dinit())


async def default_setup(template: dict[str, Any]) -> None:
    """Default setup function that initializes the environment for coding tasks."""
    logger.info("=== ENVIRONMENT SETUP DEBUG ===")
    logger.info(f"Template: {template}")

    # [OPTIONAL] Add custom hosts entry (if your project needs it)
    # Example: for projects requiring local domain names
    # with open("/etc/hosts", "a") as hosts_file:
    #     hosts_file.write("127.0.0.1 [YOUR_LOCAL_DOMAIN]\n")

    # Start dinit services
    await start_dinit()
    logger.info("Services started successfully")

    setup_codebase(
        base=template["base"],
        test=template["test"],
        golden=template["golden"],
    )

    # Wait for XFCE to fully start before setting up Chromium
    logger.info(f"Waiting {XFCE_STARTUP_DELAY} seconds for XFCE to start...")
    await asyncio.sleep(XFCE_STARTUP_DELAY)