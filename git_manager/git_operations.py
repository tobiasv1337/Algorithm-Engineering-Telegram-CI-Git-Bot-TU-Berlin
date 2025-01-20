import os
import subprocess
import json
from utils.file_operations import save_chat_config, load_chat_config

# Centralized file for storing last commits
LAST_COMMITS_FILE = "data/last_commits.json"

# Ensure the data directory exists
os.makedirs(os.path.dirname(LAST_COMMITS_FILE), exist_ok=True)


# Repository Path

def get_repo_path(chat_id):
    """
    Get the repository path for a given chat ID.
    """
    return f"data/{chat_id}/repo"


# Last Commit Management

def load_last_commit(chat_id, branch="submit"):
    """
    Load the last commit hash for a given chat ID and branch from the centralized JSON file.
    """
    if not os.path.exists(LAST_COMMITS_FILE):
        return None

    with open(LAST_COMMITS_FILE, "r") as file:
        last_commits = json.load(file)

    return last_commits.get(str(chat_id), {}).get(branch, None)

def save_last_commit(chat_id, branch, commit_hash):
    """
    Save the last commit hash for a given chat ID and branch to the centralized JSON file.
    """
    if os.path.exists(LAST_COMMITS_FILE):
        with open(LAST_COMMITS_FILE, "r") as file:
            last_commits = json.load(file)
    else:
        last_commits = {}

    if str(chat_id) not in last_commits:
        last_commits[str(chat_id)] = {}

    last_commits[str(chat_id)][branch] = commit_hash

    with open(LAST_COMMITS_FILE, "w") as file:
        json.dump(last_commits, file, indent=4)


# Repository Operations

def get_latest_commit(chat_id, branch, telegram_bot):
    """
    Get the latest commit hash on the specified branch for a given chat ID.
    """
    repo_path = get_repo_path(chat_id)
    try:
        commit_hash = subprocess.check_output(
            ["git", "-C", repo_path, "rev-parse", f"origin/{branch}"],
            text=True
        ).strip()
        return commit_hash
    except subprocess.CalledProcessError as e:
        warning_message = f"⚠️ *Git Warning: Branch Missing*\nBranch: `{branch}`\nDetails: {str(e)}"
        print(warning_message)
        telegram_bot.send_message(chat_id, warning_message)
        return None

def fetch_all_branches(chat_id, telegram_bot):
    """
    Fetch all branches from the remote repository for the given chat ID.
    """
    repo_path = get_repo_path(chat_id)
    try:
        subprocess.run(["git", "-C", repo_path, "fetch", "--all"], check=True)
    except subprocess.CalledProcessError as e:
        error_message = f"❌ *Git Error: Fetch Failed*\n\n{str(e)}"
        print(error_message)
        telegram_bot.send_message(chat_id, error_message)
        raise RuntimeError("Error fetching branches") from e

def get_commit_message(chat_id, commit_hash):
    """
    Retrieve the commit message for the specified commit hash in the user's repository.
    """
    repo_path = get_repo_path(chat_id)
    try:
        commit_message = subprocess.check_output(
            ["git", "-C", repo_path, "log", "-1", "--pretty=%B", commit_hash],
            text=True
        ).strip()
        return commit_message
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Failed to retrieve commit message for {commit_hash}: {str(e)}")

def reset_to_commit(chat_id, branch, commit_hash, telegram_bot):
    """
    Reset the repository to the specified commit for the given chat ID.
    """
    repo_path = get_repo_path(chat_id)
    try:
        subprocess.run(["git", "-C", repo_path, "checkout", branch], check=True)
        subprocess.run(["git", "-C", repo_path, "reset", "--hard", commit_hash], check=True)
        print(f"Reset branch {branch} to commit {commit_hash}")
    except subprocess.CalledProcessError as e:
        error_message = (
            f"❌ *Git Error: Reset Failed*\n"
            f"Branch: `{branch}`\n"
            f"Commit: `{commit_hash}`\n"
            f"Details: {str(e)}"
        )
        telegram_bot.send_message(chat_id, error_message)
        raise RuntimeError(f"Error resetting branch {branch} to commit {commit_hash}") from e

def get_tracked_branches(chat_id, telegram_bot):
    """
    Retrieve the list of branches to track for the given chat ID.
    Defaults to the primary branch specified in the global configuration.
    Sends appropriate error messages for missing configurations or fallback usage.
    """
    global_config = load_chat_config(chat_id)
    primary_branch = global_config.get("PRIMARY_BRANCH", "main")

    primary_branch_commit = get_latest_commit(chat_id, primary_branch, telegram_bot)
    if primary_branch_commit:
        try:
            # Load configuration from the specific commit
            config = load_config_from_commit(chat_id, primary_branch_commit)
            if config and "branches" in config:
                return config["branches"]
        except FileNotFoundError:
            error_message = (
                f"❌ *Configuration Missing*\n"
                f"The `submission_config.json` file is missing from the latest commit on branch `{primary_branch}`.\n"
                f"Please add the configuration file and push the changes."
            )
            telegram_bot.send_message(chat_id, error_message)

    fallback_message = (
        f"⚠️ *Using Fallback Branch*\n"
        f"Tracking the primary branch `{primary_branch}` as no other branches were specified."
    )
    telegram_bot.send_message(chat_id, fallback_message)

    # Default to the primary branch if no tracking branches are found
    return [primary_branch]

def load_config_from_commit(chat_id, commit_hash, config_filename="submission_config.json"):
    """
    Load submission configuration from a specific commit.
    """
    repo_path = get_repo_path(chat_id)
    try:
        config_data = subprocess.check_output(["git", "-C", repo_path, "show", f"{commit_hash}:{config_filename}"])
        return json.loads(config_data)
    except subprocess.CalledProcessError:
        raise FileNotFoundError(f"Configuration file '{config_filename}' not found in commit {commit_hash}.")


# Auto Merge

def perform_auto_merge(chat_id, branch, grouped_results, commit_hash, telegram_bot):
    """
    Automatically merge the specified branch into PRIMARY_BRANCH after successful testing.
    Includes a short summary of test results in the commit message.
    Only performs the merge if there are no conflicts.
    """
    # Get repository path and primary branch
    repo_path = get_repo_path(chat_id)
    global_config = load_chat_config(chat_id)
    primary_branch = global_config.get("PRIMARY_BRANCH", "main")

    try:
        # Step 1: Calculate the total number of tests and passed tests
        total_tests = sum(len(group["tests"]) for group in grouped_results.values())
        passed_tests = sum(
            1 for group in grouped_results.values() for test in group["tests"] if test["result"].lower() == "ok"
        )
        test_summary = f"Tests Passed: {passed_tests}/{total_tests}"

        # Step 2: Fetch the latest changes for the branch
        fetch_result = subprocess.run(
            ["git", "-C", repo_path, "fetch", "origin", branch],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if fetch_result.returncode != 0:
            telegram_bot.send_message(
                chat_id,
                f"❌ *Auto-Merge Failed*\n"
                f"Failed to fetch the latest changes for `{branch}`. Merge aborted.\n"
                f"Details:\n```\n{fetch_result.stderr.strip()}\n```"
            )
            return

        # Step 3: Reset the branch to the specified commit hash
        reset_result = subprocess.run(
            ["git", "-C", repo_path, "checkout", "-B", branch, commit_hash],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if reset_result.returncode != 0:
            telegram_bot.send_message(
                chat_id,
                f"❌ *Auto-Merge Failed*\n"
                f"Failed to reset branch `{branch}` to commit `{commit_hash}`. Merge aborted.\n"
                f"Details:\n```\n{reset_result.stderr.strip()}\n```"
            )
            return

        # Step 4: Checkout the primary branch
        subprocess.run(["git", "-C", repo_path, "checkout", primary_branch], check=True)

        # Step 5: Pull the latest changes for the primary branch
        pull_result = subprocess.run(
            ["git", "-C", repo_path, "pull", "origin", primary_branch],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if pull_result.returncode != 0:
            telegram_bot.send_message(
                chat_id,
                f"❌ *Auto-Merge Failed*\n"
                f"Failed to pull the latest changes for `{primary_branch}`. Merge aborted.\n"
                f"Details:\n```\n{pull_result.stderr.strip()}\n```"
            )
            return

        # Step 6: Merge the branch into the primary branch with --no-commit and --no-ff
        merge_result = subprocess.run(
            ["git", "-C", repo_path, "merge", "--no-commit", "--no-ff", branch],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if "CONFLICT" in merge_result.stderr:
            telegram_bot.send_message(
                chat_id,
                f"⚠️ *Merge Conflict Detected*\n"
                f"Branch `{branch}` could not be merged into `{primary_branch}` due to conflicts.\n"
                f"Details:\n```\n{merge_result.stderr.strip()}\n```"
            )
            # Abort the merge
            subprocess.run(["git", "-C", repo_path, "merge", "--abort"], check=True)
            return

        # Step 7: Commit the merge
        commit_message = f"Merge branch '{branch}' into `{primary_branch}`\n\n{test_summary}"
        subprocess.run(["git", "-C", repo_path, "commit", "-m", commit_message], check=True)

        # Step 8: Push the merged changes to the remote
        push_result = subprocess.run(
            ["git", "-C", repo_path, "push", "origin", primary_branch],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if push_result.returncode != 0:
            telegram_bot.send_message(
                chat_id,
                f"❌ *Push Failed*\n"
                f"The merged changes for `{primary_branch}` could not be pushed to the remote.\n"
                f"Details:\n```\n{push_result.stderr.strip()}\n```"
            )
            return

        # Step 9: Notify user of successful merge
        telegram_bot.send_message(
            chat_id,
            f"✅ *Auto-Merge Successful*\n"
            f"Branch `{branch}` was successfully merged into `{primary_branch}`.\n"
            f"{test_summary}"
        )
    except subprocess.CalledProcessError as e:
        # Handle unexpected errors during merge and notify via Telegram
        telegram_bot.send_message(
            chat_id,
            f"❌ *Auto-Merge Failed*\n"
            f"Error during merging branch `{branch}` into `{primary_branch}`.\n"
            f"Details: {str(e)}"
        )
        raise