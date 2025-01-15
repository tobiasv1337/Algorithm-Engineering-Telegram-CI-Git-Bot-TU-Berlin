import subprocess
import json
from config.config import Config
from api.telegram import send_telegram_message

def fetch_all_branches():
    """Fetch all branches from the remote repository and handle fetch errors."""
    try:
        subprocess.run(["git", "-C", Config.REPO_PATH, "fetch", "--all"], check=True)
    except subprocess.CalledProcessError as e:
        error_message = f"❌ *Git Error: Fetch Failed*\n\n{str(e)}"
        print(error_message)
        send_telegram_message(error_message)
        raise RuntimeError("Error fetching branches") from e

def get_latest_commit(branch):
    """Get the latest commit hash on the specified branch. Return None if the branch does not exist."""
    try:
        return subprocess.check_output(
            ["git", "-C", Config.REPO_PATH, "rev-parse", f"origin/{branch}"]
        ).strip().decode('utf-8')
    except subprocess.CalledProcessError as e:
        warning_message = f"⚠️ *Git Warning: Branch Missing*\nBranch: `{branch}`\nDetails: {str(e)}"
        print(warning_message)
        send_telegram_message(warning_message)
        return None

def reset_to_commit(commit_hash):
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
        send_telegram_message(error_message)
        raise RuntimeError(f"Error checking out to commit {commit_hash}") from e

def load_config_from_commit(commit_hash):
    """Load submission configuration from a specific commit."""
    try:
        config_data = subprocess.check_output(["git", "-C", Config.REPO_PATH, "show", f"{commit_hash}:submission_config.json"])
        return json.loads(config_data)
    except subprocess.CalledProcessError:
        message = f"Configuration file 'submission_config.json' not found in commit {commit_hash}."
        print(message)
        send_telegram_message(message)
        return None

def get_tracked_branches():
    """Retrieve the list of branches to track from the last commit's configuration on PRIMARY_BRANCH."""
    primary_branch_commit = get_latest_commit(Config.PRIMARY_BRANCH)
    if primary_branch_commit:
        config = load_config_from_commit(primary_branch_commit)
        if config and "branches" in config:
            return config["branches"]
    return [Config.PRIMARY_BRANCH]  # Default to PRIMARY_BRANCH if branches are not specified