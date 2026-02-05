# Instructions

This walkthrough will get you set up running a sample task from our included submodule, which asks the agent to fix a small bug in an HTTP server. This template is meant for tasks that ask the agent to make modifications to code in a live shell environment, after which a set of hidden unit tests or integration tests will be run to verify task completion. At the end of this walkthrough, you'll be able to see Claude Sonnet 4.5 solve one such task in real time via HUD's user interface.

## Local

These instructions are for running tasks locally. The telemetry from your runs will be uploaded to HUD's platform.

### 1. Clone and Initialize

```bash
git clone https://github.com/hud-evals/coding-template
cd coding-template
git submodule update --init
uv sync
```

### 2. Build and Run

```bash
hud build .
hud dev --port 8765
```
In a seperate terminal:
```
python local_test.py
```

## Remote

These instructions are for running remote jobs. You only have access to these if you are a HUD enterprise customer: contact founders@hud.ai to learn more.

### 1. Deploy to Platform

If you haven't already, connect this repo to hud.ai:

1. Clone this template repository
2. Go to [hud.ai](https://hud.ai) → **Environments** → **New Environment**
3. Connect your GitHub repo
4. (Optional) Set `CODING_GITHUB_TOKEN` build arg if using a private submodule
5. Your environment builds automatically on each push

Once deployed, your environment is accessible by its slug (e.g., `my-org/coding`).

### 2. Create a new taskset and add your first task

1. Go to **Tasksets** → **New Taskset** and create a new taskset
2. Go to your environment and enter `sample-json-bug` as the scenario. This corresponds to the task in `coding-template/tasks/basic.py`.
3. Click on "Create Task" and add this to your taskset.

### 3. Run your first task

1. Go to your taskset. Under "Tasks", you should be able to see your `sample-json-bug` task.
2. Click on "Run Taskset". Click on "Claude Sonnet 4.5" and set the "Max Steps" to 20 and "Group Size" to 5.
3. Click on "Run [N] Tasks", which should open the page for the job you've just launched.

### 4. Create your own tasks

You can create your own tasks by adding new scenarios in `tasks/basic.py` (or `medium.py`, `hard.py`).

To create tasks for your own project:

1. Create `baseline`, `test`, and `golden` branches in your target repo

2. Build with your repo URL:
   ```bash
   hud build . --build-arg REPO_URL=https://github.com/your-org/your-repo
   ```

4. Add runtime dependencies in `Dockerfile.hud` if needed

We include several graders in `grading/graders.py`. You may add more if your needs grow beyond the existing graders.
