# Instructions

This walkthrough will get you set up running a sample task from our [source repo](https://github.com/hud-evals/coding-template-sample), which asks the agent to fix a small bug in an HTTP server.

## 1. Deploy to Platform

If you haven't already, connect this repo to hud.ai:

1. Push to GitHub
2. Go to [hud.ai](https://hud.ai) → **New** → **Environment**
3. Connect your GitHub repo
4. Your environment builds automatically on each push. You can also build it manually via [your environment] > Build.

Once deployed, your environment is accessible by its slug (e.g., `my-org/coding`).


## 2. Create a new taskset and add your first task

1. Go to Tasksets > New Tasksets and create a new taskset
2. Go to your environment and enter `sample_json_bug` as the `problem_id`. You'll see that this corresponds to the single existing task in `coding-template/tasks/basic.py`.
3. Click on "Create Task" and add this to your taskset.

## 3. Run your first task

1. Go to your taskset. Under "Tasks", you should be able to see your `sample_json_bug` task.
2. Click on "Run Taskset". Click on "Claude Sonnet 4.5" and set the "Max Steps" to 20 and "Group Size" to 5.
3. Click on "Run [N] Tasks", which should open the page for the job you've just launched.

## 4. Create your own tasks

You can create your own tasks by adding new items in `basic.py` using the template we use for the starter task.
- To create new tasks, you'll need a `baseline` and `test` branch in your own source repo. You may also want to maintain a `golden` branch to verify that your tests are correct.
- If you want to add runtime dependencies, you'll want to modify `Dockerfile` to install these or alternatively include them in the `baseline` branch for your task in your source repo.
- We include four basic graders in `grading/graders.py`. You may want to add more graders if your needs grow beyond the limited scope of the existing graders.
