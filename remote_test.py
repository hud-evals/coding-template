"""Remote test script for the coding environment.

This script demonstrates how to:
1. Load tasks from a local JSON file
2. Run evaluations on remote deployed environments
3. Save tasks to the HUD platform
"""
import asyncio

import hud
from hud.agents import OpenAIChatAgent
from hud.datasets import load_tasks, save_tasks


async def test_local_json():
    """Load tasks from remote_tasks.json and run locally."""
    print("=== Option A: Load from JSON ===")

    tasks = load_tasks("remote_tasks.json")
    print(f"Loaded {len(tasks)} tasks from JSON")

    # Run first task
    async with hud.eval(tasks[0], trace=True) as ctx:
        agent = OpenAIChatAgent.create(model="gpt-4o")  # https://hud.ai/models
        await agent.run(ctx, max_steps=20)


async def test_remote_dataset():
    """Load tasks from HUD platform by slug."""
    print("\n=== Option B: Load from Platform ===")

    # Load a dataset you've created on hud.ai
    tasks = load_tasks("my-org/coding-tasks:v1")
    print(f"Loaded {len(tasks)} tasks from platform")

    async with hud.eval(tasks, trace=True) as ctx:
        agent = OpenAIChatAgent.create(model="gpt-4o")  # https://hud.ai/models
        await agent.run(ctx)


async def upload_tasks():
    """Upload local tasks to the HUD platform."""
    print("\n=== Upload Tasks to Platform ===")

    # Load from local JSON
    tasks = load_tasks("remote_tasks.json")

    # Save to platform with a slug
    await save_tasks("my-coding-tasks", tasks)
    print("Tasks uploaded successfully!")


async def main():
    await test_local_json()
    # Uncomment to test remote features:
    # await test_remote_dataset()
    # await upload_tasks()


if __name__ == "__main__":
    asyncio.run(main())
