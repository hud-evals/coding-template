"""Local test script for the coding environment.

Development workflow:
1. Start the container with hot-reload: hud dev -w tasks -w grading --port 8765
2. Run this script: python local_test.py
3. Edit tasks/*.py or grading/*.py - container auto-reloads
4. Re-run this script to test changes

Scenarios call internal tools (_grade_solution) on the container.
Task definitions and grading logic run inside the container (hot-reloaded).
"""
import asyncio
import os

import hud
from hud import Environment
from hud.agents import OpenAIChatAgent
from hud.settings import settings
from openai import AsyncOpenAI

# Import scenario registration (shares helpers with env.py and cli.py)
from scenarios import register_scenarios

# Use HUD inference gateway - see all models at https://hud.ai/models
client = AsyncOpenAI(base_url="https://inference.hud.ai", api_key=settings.api_key)

# Connect to running container
DEV_URL = os.getenv("HUD_DEV_URL", "http://localhost:8765/mcp")

env = Environment("coding")
env.connect_url(DEV_URL)

# Register scenarios (they use call_tool which goes to the container)
register_scenarios(env)


# ============================================================================
# Tests
# ============================================================================


async def test_tools_standalone():
    """Test environment tools directly (no scenario)."""
    print("=== Test 1: Standalone Tools ===")
    print(f"Connecting to: {DEV_URL}")

    async with env:
        tools = env.as_tools()
        # Filter out internal tools (prefixed with _)
        visible_tools = [t for t in tools if not t.name.startswith("_")]
        print(f"Agent-visible tools: {[t.name for t in visible_tools]}")
        print(f"Internal tools: {[t.name for t in tools if t.name.startswith('_')]}")

        # Test bash
        result = await env.call_tool("bash", command="echo 'Hello from coding env'")
        print(f"Bash result: {result}")


async def test_solve_task_manual():
    """Test solve-task scenario with manual OpenAI completions loop."""
    print("\n=== Test 2: Solve Task (Manual Agent Loop) ===")

    async with env:
        task = env("solve-task", problem_id="template_basic_task")

        async with hud.eval(task, trace=True) as ctx:
            messages = [{"role": "user", "content": ctx.prompt}]

            for _ in range(10):
                response = await client.chat.completions.create(
                    model="gpt-4o",  # https://hud.ai/models
                    messages=messages,
                    tools=ctx.as_openai_chat_tools(),
                )
                msg = response.choices[0].message

                if not msg.tool_calls:
                    print(f"Agent finished with: {msg.content}")
                    break

                messages.append(msg)
                for tc in msg.tool_calls:
                    result = await ctx.call_tool(tc)
                    messages.append(result)


async def test_solve_task_agent():
    """Test solve-task scenario with OpenAIChatAgent."""
    print("\n=== Test 3: Solve Task (OpenAIChatAgent) ===")

    async with env:
        task = env("solve-task", problem_id="template_basic_task")

        async with hud.eval(task, trace=True) as ctx:
            agent = OpenAIChatAgent.create(model="gpt-4o")  # https://hud.ai/models
            await agent.run(ctx, max_steps=20)


async def test_distribution():
    """Test multiple tasks with variants and groups for A/B testing."""
    print("\n=== Test 4: Distribution (Variants + Groups) ===")

    async with env:
        tasks = [
            env("solve-task", problem_id="template_basic_task"),
            env("solve-task", problem_id="template_medium_task"),
        ]
        variants = {"model": ["gpt-4o-mini", "gpt-4o"]}
        group = 2

        async with hud.eval(tasks, variants=variants, group=group, trace=True) as ctx:
            agent = OpenAIChatAgent.create(model=ctx.variants["model"])
            await agent.run(ctx, max_steps=20)


async def main():
    print("Coding Environment - Local Test")
    print("=" * 50)
    print(f"Container URL: {DEV_URL}")
    print("Make sure the container is running:")
    print("  hud dev -w tasks -w grading --port 8765")
    print("=" * 50)
    print()

    await test_tools_standalone()

    # Uncomment to run full scenarios:
    # await test_solve_task_manual()
    # await test_solve_task_agent()
    # await test_distribution()


if __name__ == "__main__":
    asyncio.run(main())
