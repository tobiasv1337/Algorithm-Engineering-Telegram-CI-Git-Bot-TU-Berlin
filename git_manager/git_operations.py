import os
import subprocess
import json
from config.config import Config

LAST_COMMITS_FILE = "last_commits.json"  # File to store last processed commit for each branch

def load_last_commits():
    """Load the last processed commit hashes from a file."""
    if os.path.exists(LAST_COMMITS_FILE):
        with open(LAST_COMMITS_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_last_commits(last_commit_per_branch):
    """Save the last processed commit hashes to a file."""
    with open(LAST_COMMITS_FILE, 'w') as f:
        json.dump(last_commit_per_branch, f)

def fetch_all_branches(telegram_bot):
    """Fetch all branches from the remote repository and handle fetch errors."""
    try:
        subprocess.run(["git", "-C", Config.REPO_PATH, "fetch", "--all"], check=True)
    except subprocess.CalledProcessError as e:
        error_message = f"❌ *Git Error: Fetch Failed*\n\n{str(e)}"
        print(error_message)
        telegram_bot.send_message(error_message)
        raise RuntimeError("Error fetching branches") from e

def get_latest_commit(branch, telegram_bot):
    """Get the latest commit hash on the specified branch. Return None if the branch does not exist."""
    try:
        return subprocess.check_output(
            ["git", "-C", Config.REPO_PATH, "rev-parse", f"origin/{branch}"]
        ).strip().decode('utf-8')
    except subprocess.CalledProcessError as e:
        warning_message = f"⚠️ *Git Warning: Branch Missing*\nBranch: `{branch}`\nDetails: {str(e)}"
        print(warning_message)
        telegram_bot.send_message(warning_message)
        return None

def reset_to_commit(commit_hash, telegram_bot):
    """
    Reset the repository to the specified commit.
    Ensures the working directory matches the detected commit.
    """
    try:
        subprocess.run(["git", "-C", Config.REPO_PATH, "checkout", commit_hash], check=True)
        print(f"Checked out to commit {commit_hash}")
    except subprocess.CalledProcessError as e:
        error_message = (
            f"❌ *Git Error: Checkout Failed*\n"
            f"Commit: `{commit_hash}`\n"
            f"Details: {str(e)}"
        )
        print(error_message)
        telegram_bot.send_message(error_message)
        raise RuntimeError(f"Error checking out to commit {commit_hash}") from e

def load_config_from_commit(commit_hash, telegram_bot):
    """Load submission configuration from a specific commit."""
    try:
        config_data = subprocess.check_output(["git", "-C", Config.REPO_PATH, "show", f"{commit_hash}:submission_config.json"])
        return json.loads(config_data)
    except subprocess.CalledProcessError:
        message = f"Configuration file 'submission_config.json' not found in commit {commit_hash}."
        print(message)
        telegram_bot.send_message(message)
        return None

def get_tracked_branches():
    """Retrieve the list of branches to track from the last commit's configuration on PRIMARY_BRANCH."""
    primary_branch_commit = get_latest_commit(Config.PRIMARY_BRANCH)
    if primary_branch_commit:
        config = load_config_from_commit(primary_branch_commit)
        if config and "branches" in config:
            return config["branches"]
    return [Config.PRIMARY_BRANCH]  # Default to PRIMARY_BRANCH if branches are not specified

def perform_auto_merge(branch, grouped_results, commit_hash, telegram_bot):
    """
    Automatically merge the specified branch into PRIMARY_BRANCH after successful testing.
    Includes a short summary of test results in the commit message.
    Only performs the merge if there are no conflicts.
    """
    try:
        # Calculate the total number of tests and passed tests
        total_tests = sum(len(group["tests"]) for group in grouped_results.values())
        passed_tests = sum(
            1 for group in grouped_results.values() for test in group["tests"] if test["result"].lower() == "ok"
        )

        # Prepare the test summary for the commit message
        test_summary = f"Tests Passed: {passed_tests}/{total_tests}"

        # Step 1: Fetch the latest changes for the submit branch to ensure it's up to date
        fetch_result = subprocess.run(
            ["git", "-C", Config.REPO_PATH, "fetch", "origin", branch],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if fetch_result.returncode != 0:
            telegram_bot.send_message(
                f"❌ *Auto-Merge Failed*\n"
                f"Failed to fetch the latest changes for `{branch}`. Merge aborted.\n"
                f"Details:\n```\n{fetch_result.stderr.strip()}\n```"
            )
            return

        # Step 2: Reset the submit branch to the specific commit hash
        reset_result = subprocess.run(
            ["git", "-C", Config.REPO_PATH, "checkout", "-B", branch, commit_hash],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if reset_result.returncode != 0:
            telegram_bot.send_message(
                f"❌ *Auto-Merge Failed*\n"
                f"Failed to reset branch `{branch}` to commit `{commit_hash}`. Merge aborted.\n"
                f"Details:\n```\n{reset_result.stderr.strip()}\n```"
            )
            return

        # Step 3: Checkout the PRIMARY_BRANCH branch
        subprocess.run(["git", "-C", Config.REPO_PATH, "checkout", Config.PRIMARY_BRANCH], check=True)

        # Step 4: Pull the latest changes from the remote to ensure the local branch is up-to-date
        pull_result = subprocess.run(
            ["git", "-C", Config.REPO_PATH, "pull", "origin", Config.PRIMARY_BRANCH],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if pull_result.returncode != 0:
            telegram_bot.send_message(
                f"❌ *Auto-Merge Failed*\n"
                f"Failed to pull the latest changes for `{Config.PRIMARY_BRANCH}`. Merge aborted.\n"
                f"Details:\n```\n{pull_result.stderr.strip()}\n```"
            )
            return

        # Step 5: Merge the target branch into PRIMARY_BRANCH with --no-commit and --no-ff to detect conflicts
        merge_result = subprocess.run(
            ["git", "-C", Config.REPO_PATH, "merge", "--no-commit", "--no-ff", branch],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        # Check for conflicts
        if "CONFLICT" in merge_result.stderr:
            telegram_bot.send_message(
                f"⚠️ *Merge Conflict Detected*\n"
                f"Branch `{branch}` could not be merged into `{Config.PRIMARY_BRANCH}` due to conflicts.\n"
                f"Details:\n```\n{merge_result.stderr.strip()}\n```"
            )

            # Abort the merge
            subprocess.run(["git", "-C", Config.REPO_PATH, "merge", "--abort"], check=True)
            return

        # Step 6: Commit and complete the merge if no conflicts
        commit_message = f"Merge branch '{branch}' into `{Config.PRIMARY_BRANCH}`\n\n{test_summary}"
        subprocess.run(["git", "-C", Config.REPO_PATH, "commit", "-m", commit_message], check=True)

        # Step 7: Push the merged changes to the remote
        push_result = subprocess.run(
            ["git", "-C", Config.REPO_PATH, "push", "origin", Config.PRIMARY_BRANCH],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if push_result.returncode != 0:
            telegram_bot.send_message(
                f"❌ *Push Failed*\n"
                f"The merged changes for `{Config.PRIMARY_BRANCH}` could not be pushed to the remote.\n"
                f"Details:\n```\n{push_result.stderr.strip()}\n```"
            )
            return

        # Send Telegram notification about success
        telegram_bot.send_message(f"✅ *Auto-Merge Successful*\n"
                              f"Branch `{branch}` was successfully merged into `{Config.PRIMARY_BRANCH}`.\n"
                              f"{test_summary}")
    except subprocess.CalledProcessError as e:
        # Handle unexpected errors during merge and notify via Telegram
        telegram_bot.send_message(f"❌ *Auto-Merge Failed*\n"
                              f"Error during merging branch `{branch}` into `{Config.PRIMARY_BRANCH}`.\n"
                              f"Details: {str(e)}")