import os
import subprocess
import json
from utils.file_operations import load_chat_config

# Centralized file for storing last commits
LAST_COMMITS_FILE = "data/last_commits.json"

# Ensure the data directory exists
os.makedirs(os.path.dirname(LAST_COMMITS_FILE), exist_ok=True)


# Path Helper Functions
def get_chat_dir(chat_id):
    """
    Get the data directory for a given chat ID.
    """
    return os.path.join("data", str(chat_id))


def get_repo_path(chat_id):
    """
    Get the repository path for a given chat ID.
    """
    return os.path.join(get_chat_dir(chat_id), "repo")


# SSH Key Management
def generate_ssh_key(chat_id):
    """
    Generate an SSH key pair for the user and store it in their data directory.
    """
    chat_dir = get_chat_dir(chat_id)
    ssh_key_path = os.path.join(chat_dir, "id_rsa")

    if not os.path.exists(chat_dir):
        os.makedirs(chat_dir)

    subprocess.run(["ssh-keygen", "-t", "rsa", "-b", "4096", "-f", ssh_key_path, "-N", ""])

    return ssh_key_path


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


# Helper Function for Git Commands
def execute_git_command(chat_id, command, telegram_bot=None, failure_message=None):
    """
    Execute a Git command with the appropriate SSH key for the given chat ID.
    """
    repo_path = get_repo_path(chat_id)
    config = load_chat_config(chat_id)
    access_type = config.get("access_type", "https")  # Default to HTTPS

    # Prepare environment for SSH if needed
    env = os.environ.copy()
    if access_type == "ssh":
        ssh_key_path = os.path.join(get_chat_dir(chat_id), "id_rsa")
        git_ssh_command = f"ssh -i {ssh_key_path} -o IdentitiesOnly=yes"
        env["GIT_SSH_COMMAND"] = git_ssh_command

    try:
        # Execute the Git command
        result = subprocess.check_output(
            ["git", "-C", repo_path] + command,
            env=env,
            text=True,
        ).strip()
        return result
    except subprocess.CalledProcessError as e:
        if telegram_bot and failure_message:
            telegram_bot.send_message(chat_id, failure_message)
        raise RuntimeError(f"Git command failed: {e}")


# Repository Operations
def clone_repository(chat_id, repo_url, telegram_bot):
    """
    Clone a repository using the appropriate authentication method (HTTPS or SSH).
    """
    repo_path = get_repo_path(chat_id)
    config = load_chat_config(chat_id)
    access_type = config.get("access_type")

    if not os.path.exists(repo_path):
        os.makedirs(repo_path)

    try:
        if access_type == "ssh":
            ssh_key_path = os.path.join(get_chat_dir(chat_id), "id_rsa")
            git_ssh_command = f"ssh -i {ssh_key_path} -o IdentitiesOnly=yes"
            env = os.environ.copy()
            env["GIT_SSH_COMMAND"] = git_ssh_command
            subprocess.run(["git", "clone", repo_url, repo_path], check=True, env=env)

        elif access_type == "https":
            # Embed credentials directly in the URL
            git_username = config.get("git_username")
            git_password = config.get("git_password")
            if not git_username or not git_password:
                raise ValueError("Missing Git username or password for HTTPS authentication.")

            # Create a URL with credentials
            repo_url_with_credentials = repo_url.replace(
                "https://", f"https://{git_username}:{git_password}@"
            )

            # Clone the repository
            subprocess.run(["git", "clone", repo_url_with_credentials, repo_path], check=True)

        else:
            # Handle cases with no authentication
            subprocess.run(["git", "clone", repo_url, repo_path], check=True)

    except subprocess.CalledProcessError:
        # Mask credentials in the error message
        safe_repo_url = mask_url_credentials(repo_url)
        telegram_bot.send_message(
            chat_id,
            f"❌ *Git Error: Clone Failed*\nRepository: `{safe_repo_url}`\nDetails: Git command failed."
        )
        raise RuntimeError(f"Failed to clone repository: {safe_repo_url}")

    except Exception as e:
        telegram_bot.send_message(
            chat_id,
            f"❌ *Setup Error*: {str(e)}"
        )
        raise RuntimeError(f"Setup error during cloning: {e}")


def mask_url_credentials(url):
    """
    Mask credentials in a URL for secure error reporting.
    """
    if "@" in url:
        # Split the URL to isolate the credentials
        scheme, rest = url.split("://", 1)
        if "@" in rest:
            credentials, host_and_path = rest.split("@", 1)
            masked_credentials = "****:****"
            return f"{scheme}://{masked_credentials}@{host_and_path}"
    return url


def fetch_all_branches(chat_id, telegram_bot):
    """
    Fetch all branches from the remote repository for the given chat ID.
    """
    try:
        execute_git_command(chat_id, ["fetch", "--all"], telegram_bot, "❌ *Git Error: Fetch Failed*")
    except RuntimeError as e:
        raise RuntimeError("Error fetching branches") from e


def get_latest_commit(chat_id, branch, telegram_bot):
    """
    Get the latest commit hash on the specified branch for a given chat ID.
    """
    try:
        return execute_git_command(
            chat_id,
            ["rev-parse", f"origin/{branch}"],
            telegram_bot,
            f"⚠️ *Git Warning: Branch Missing*\nBranch: `{branch}` is unavailable."
        )
    except RuntimeError:
        return None


def get_commit_message(chat_id, commit_hash, telegram_bot=None):
    """
    Retrieve the commit message for the specified commit hash in the user's repository.
    """
    failure_message = (
        f"❌ *Git Error: Commit Message Retrieval Failed*\n"
        f"Commit: `{commit_hash}`\n"
        f"Unable to retrieve the commit message. Please ensure the commit exists."
    )
    return execute_git_command(
        chat_id,
        ["log", "-1", "--pretty=%B", commit_hash],
        telegram_bot,
        failure_message
    )


def reset_to_commit(chat_id, branch, commit_hash, telegram_bot):
    """
    Reset the repository to the specified commit for the given chat ID.
    """
    try:
        execute_git_command(chat_id, ["checkout", branch])
        execute_git_command(chat_id, ["reset", "--hard", commit_hash])
    except RuntimeError as e:
        telegram_bot.send_message(
            chat_id,
            f"❌ *Git Error: Reset Failed*\nBranch: `{branch}`\nCommit: `{commit_hash}`\nDetails: {str(e)}"
        )
        raise RuntimeError(f"Error resetting branch {branch} to commit {commit_hash}")


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
            config = load_config_from_commit(chat_id, primary_branch_commit)
            if config and "branches" in config:
                return config["branches"]
        except FileNotFoundError:
            telegram_bot.send_message(
                chat_id,
                f"❌ *Configuration Missing*\nMissing `submission_config.json` on `{primary_branch}`."
            )

    telegram_bot.send_message(
        chat_id,
        f"⚠️ *Using Fallback Branch*\nDefaulting to `{primary_branch}`."
    )
    # Default to the primary branch if no tracking branches are found
    return [primary_branch]


def load_config_from_commit(chat_id, commit_hash, config_filename="submission_config.json"):
    """
    Load submission configuration from a specific commit.
    """
    try:
        config_data = execute_git_command(
            chat_id,
            ["show", f"{commit_hash}:{config_filename}"],
        )
        return json.loads(config_data)
    except RuntimeError:
        raise FileNotFoundError(f"Configuration file '{config_filename}' not found in commit {commit_hash}.")


def perform_auto_merge(chat_id, branch, grouped_results, commit_hash, telegram_bot):
    """
    Automatically merge the specified branch into PRIMARY_BRANCH after successful testing.
    Includes a short summary of test results in the commit message.
    Only performs the merge if there are no conflicts.
    """
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
        fetch_failure_message = (
            f"❌ *Auto-Merge Failed*\n"
            f"Failed to fetch the latest changes for `{branch}`. Merge aborted."
        )
        execute_git_command(
            chat_id,
            ["fetch", "origin", branch],
            telegram_bot,
            fetch_failure_message
        )

        # Step 3: Reset the branch to the specified commit hash
        reset_failure_message = (
            f"❌ *Auto-Merge Failed*\n"
            f"Failed to reset branch `{branch}` to commit `{commit_hash}`. Merge aborted."
        )
        execute_git_command(
            chat_id,
            ["checkout", "-B", branch, commit_hash],
            telegram_bot,
            reset_failure_message
        )

        # Step 4: Checkout the primary branch
        checkout_failure_message = (
            f"❌ *Auto-Merge Failed*\n"
            f"Failed to checkout the primary branch `{primary_branch}`. Merge aborted."
        )
        execute_git_command(
            chat_id,
            ["checkout", primary_branch],
            telegram_bot,
            checkout_failure_message
        )

        # Step 5: Pull the latest changes for the primary branch
        pull_failure_message = (
            f"❌ *Auto-Merge Failed*\n"
            f"Failed to pull the latest changes for `{primary_branch}`. Merge aborted."
        )
        execute_git_command(
            chat_id,
            ["pull", "origin", primary_branch],
            telegram_bot,
            pull_failure_message
        )

        # Step 6: Merge the branch into the primary branch with --no-commit and --no-ff
        merge_failure_message = (
            f"⚠️ *Merge Conflict Detected*\n"
            f"Branch `{branch}` could not be merged into `{primary_branch}` due to conflicts."
        )
        try:
            execute_git_command(
                chat_id,
                ["merge", "--no-commit", "--no-ff", branch],
                telegram_bot,
                merge_failure_message
            )
        except RuntimeError:
            # Abort the merge in case of conflicts
            abort_failure_message = (
                f"❌ *Merge Aborted*\n"
                f"Conflict resolution failed during the merge of `{branch}` into `{primary_branch}`."
            )
            execute_git_command(chat_id, ["merge", "--abort"], telegram_bot, abort_failure_message)
            return

        # Step 7: Commit the merge
        commit_message = f"Merge branch '{branch}' into `{primary_branch}`\n\n{test_summary}"
        commit_failure_message = (
            f"❌ *Auto-Merge Failed*\n"
            f"Failed to commit the merge changes for `{branch}` into `{primary_branch}`."
        )
        execute_git_command(
            chat_id,
            ["commit", "-m", commit_message],
            telegram_bot,
            commit_failure_message
        )

        # Step 8: Push the merged changes to the remote
        push_failure_message = (
            f"❌ *Push Failed*\n"
            f"The merged changes for `{primary_branch}` could not be pushed to the remote."
        )
        execute_git_command(
            chat_id,
            ["push", "origin", primary_branch],
            telegram_bot,
            push_failure_message
        )

        # Step 9: Notify user of successful merge
        telegram_bot.send_message(
            chat_id,
            f"✅ *Auto-Merge Successful*\n"
            f"Branch `{branch}` was successfully merged into `{primary_branch}`.\n"
            f"{test_summary}"
        )
    except RuntimeError as e:
        # Notify user of unexpected errors
        telegram_bot.send_message(
            chat_id,
            f"❌ *Auto-Merge Failed*\nDetails: {str(e)}"
        )
