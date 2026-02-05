"""Local test script for the coding environment.

Development workflow:
1. Start the container with hot-reload: hud dev -w tasks -w grading --port 8765
2. Run this script: python local_test.py
3. Edit tasks/*.py or grading/*.py - container auto-reloads
4. Re-run this script to test changes
"""

import asyncio
import os

import hud
from hud.agents import OpenAIChatAgent
from hud.settings import settings
from openai import AsyncOpenAI

from env import env

# Use HUD inference gateway
client = AsyncOpenAI(base_url="https://inference.hud.ai", api_key=settings.api_key)

# Connect to running container
DEV_URL = os.getenv("HUD_DEV_URL", "http://localhost:8765/mcp")
env.connect_url(DEV_URL)


async def test_tools_standalone():
    """Test environment tools directly (no scenario)."""
    print("=== Test: Standalone Tools ===")
    print(f"Connecting to: {DEV_URL}")

    async with env:
        tools = env.as_tools()
        visible_tools = [t for t in tools if not t.name.startswith("_")]
        print(f"Agent-visible tools: {[t.name for t in visible_tools]}")

        result = await env.call_tool("bash", command="echo 'Hello from coding env'")
        print(f"Bash result: {result}")


async def test_scenario():
    """Test a scenario with an agent."""
    print("\n=== Test: sample-json-bug Scenario ===")

    async with env:
        # Use the scenario name directly
        task = env("sample-json-bug")

        async with hud.eval(task, trace=True) as ctx:
            agent = OpenAIChatAgent.create(model="gpt-4o")
            await agent.run(ctx, max_steps=20)


async def validate_golden(
    base: str = "server_fix_baseline",
    test: str = "server_fix_test",
    golden: str = "server_fix_golden",
    test_files: list[str] = ["test_server.py"],
):
    """Dry run: verify golden branch passes tests.
    
    This validates your task setup by:
    1. Checking out golden branch (the solution)
    2. Running test files
    3. Reporting pass/fail
    """
    print(f"\n=== Validate Golden Branch: {golden} ===")
    
    async with env:
        # Checkout golden branch
        print(f"Checking out: {golden}")
        result = await env.call_tool("bash", command=f"cd /home/ubuntu/project && git checkout origin/{golden}")
        print(f"Checkout: {result[:200] if len(result) > 200 else result}")
        
        # Run tests
        test_cmd = f"cd /home/ubuntu/project && python -m pytest {' '.join(test_files)} -v"
        print(f"Running: {test_cmd}")
        result = await env.call_tool("bash", command=test_cmd)
        print(result)
        
        # Check result
        if "passed" in result.lower() and "failed" not in result.lower():
            print("\n✅ Golden branch PASSES tests")
        else:
            print("\n❌ Golden branch FAILS tests - check your setup!")
        
        # Reset to baseline
        await env.call_tool("bash", command=f"cd /home/ubuntu/project && git checkout origin/{base}")
        print(f"Reset to baseline: {base}")


async def main():
    print("Coding Environment - Local Test")
    print("=" * 50)
    print(f"Container URL: {DEV_URL}")
    print("Make sure the container is running:")
    print("  hud dev -w tasks -w grading --port 8765")
    print("=" * 50)
    print()

    await test_tools_standalone()

    # Uncomment to validate golden branch passes tests:
    # await validate_golden()
    
    # Uncomment to run scenario with agent:
    # await test_scenario()


if __name__ == "__main__":
    asyncio.run(main())
