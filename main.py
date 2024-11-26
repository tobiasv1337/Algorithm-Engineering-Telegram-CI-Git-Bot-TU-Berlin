import os
import time
import json
import re
import signal
import subprocess
import requests
from bs4 import BeautifulSoup
from zipfile import ZipFile
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configuration
CHECK_INTERVAL = 10  # Check every 10 seconds
REPO_PATH = "/home/contestbot/vertex_cover"  # Set your repository path here
PRIMARY_BRANCH = "master"  # Change this to "main" or any other branch name as needed
OIOIOI_BASE_URL = "https://algeng.inet.tu-berlin.de"
OIOIOI_USERNAME = os.getenv("OIOIOI_USERNAME")
OIOIOI_PASSWORD = os.getenv("OIOIOI_PASSWORD")
OIOIOI_API_TOKEN = os.getenv("OIOIOI_API_TOKEN")  # Load API token from .env file
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

LAST_COMMITS_FILE = "last_commits.json"  # File to store last processed commit for each branch
SUBMISSION_HISTORY_FILE = "submission_history.json"  # File to store submission history

# Global variable to track requested shutdown
shutdown_flag = False

def handle_shutdown_signal(signum, frame):
    """Signal handler to stop the script gracefully."""
    global shutdown_flag
    print(f"\nSignal {signum} received. Shutting down gracefully...")
    shutdown_flag = True

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

last_commit_per_branch = load_last_commits()  # Initialize with saved data if available

def load_submission_history():
    """Load historical submission data from a file."""
    if os.path.exists(SUBMISSION_HISTORY_FILE):
        with open(SUBMISSION_HISTORY_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_submission_history(history):
    """Save historical submission data to a file."""
    with open(SUBMISSION_HISTORY_FILE, 'w') as f:
        json.dump(history, f, indent=4)

def escape_markdown(text, exclude=None):
    """Escape special characters in text for Telegram Markdown while preserving formatting."""
    if exclude is None:
        exclude = set('*_`')  # Allow bold, italic, and inline code
    escape_chars = '_*[]()~`>#+-=|{}.!'
    return ''.join(f'\\{char}' if char in escape_chars and char not in exclude else char for char in text)

def send_telegram_message(message, parse_mode="MarkdownV2", disable_web_page_preview=True):
    """
    Send a message to the Telegram group. Automatically splits long messages if needed.
    Splits at newline characters when possible.
    """
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    max_length = 4096  # Telegram's maximum message length

    def split_message_by_newline(message, max_length):
        """
        Split the message at newline characters, ensuring no part exceeds max_length.
        """
        if len(message) <= max_length:
            return [message]

        parts = []
        current_part = ""

        for line in message.split("\n"):
            # If adding the current line exceeds the limit, finalize the current part
            if len(current_part) + len(line) + 1 > max_length:
                parts.append(current_part.strip())
                current_part = ""

            current_part += line + "\n"

        # Append any remaining text as the last part
        if current_part:
            parts.append(current_part.strip())

        return parts

    # Escape special characters while keeping bold and italic
    escaped_message = escape_markdown(message, exclude={'*', '_', '`'})

    # Split message using the newline-aware function
    split_messages = split_message_by_newline(escaped_message, max_length)

    # Send each part as a separate Telegram message
    for part in split_messages:
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": part.strip(),
            "parse_mode": parse_mode,  # Pass the parse mode as a parameter
            "disable_web_page_preview": disable_web_page_preview  # Pass link preview toggle
        }
        try:
            response = requests.post(url, data=payload)
            if response.status_code == 200:
                print("Message sent to Telegram successfully.")
            else:
                print(f"Failed to send message to Telegram. Status code: {response.status_code}")
                print(f"Response: {response.text}")
        except Exception as e:
            print(f"Error sending message to Telegram: {e}")

def fetch_all_branches():
    """Fetch all branches from the remote repository and handle fetch errors."""
    try:
        subprocess.run(["git", "-C", REPO_PATH, "fetch", "--all"], check=True)
    except subprocess.CalledProcessError as e:
        message = f"Error fetching branches: {e}\nRetrying fetch on next iteration..."
        print(message)
        send_telegram_message(message)

def get_latest_commit(branch):
    """Get the latest commit hash on the specified branch. Return None if the branch does not exist."""
    try:
        return subprocess.check_output(["git", "-C", REPO_PATH, "rev-parse", f"origin/{branch}"]).strip().decode('utf-8')
    except subprocess.CalledProcessError:
        message = f"Warning: Branch '{branch}' does not exist on the remote. Skipping."
        print(message)
        send_telegram_message(message)
        return None

def load_config_from_commit(commit_hash):
    """Load submission configuration from a specific commit."""
    try:
        config_data = subprocess.check_output(["git", "-C", REPO_PATH, "show", f"{commit_hash}:submission_config.json"])
        return json.loads(config_data)
    except subprocess.CalledProcessError:
        message = f"Configuration file 'submission_config.json' not found in commit {commit_hash}."
        print(message)
        send_telegram_message(message)
        return None

def get_tracked_branches():
    """Retrieve the list of branches to track from the last commit's configuration on PRIMARY_BRANCH."""
    primary_branch_commit = get_latest_commit(PRIMARY_BRANCH)
    if primary_branch_commit:
        config = load_config_from_commit(primary_branch_commit)
        if config and "branches" in config:
            return config["branches"]
    return [PRIMARY_BRANCH]  # Default to PRIMARY_BRANCH if branches are not specified

def create_zip_files(config):
    """
    Create multiple ZIP files based on the `zip_files` configuration in the submission config.
    Returns a list of created ZIP file paths.
    """
    zip_files = config.get("zip_files", [])
    created_files = []

    for zip_config in zip_files:
        zip_name = zip_config.get("zip_name", "submission.zip")
        include_paths = zip_config.get("include_paths", [])
        zip_path = os.path.join(REPO_PATH, zip_name)

        with ZipFile(zip_path, 'w') as zipf:
            for path in include_paths:
                full_path = os.path.join(REPO_PATH, os.path.normpath(path))

                # Verify that each path is within the repository and not a symlink
                if not full_path.startswith(REPO_PATH) or os.path.islink(full_path):
                    print(f"Skipping unsafe or invalid path: '{path}'")
                    continue

                # If the path is a file, add it directly
                if os.path.isfile(full_path):
                    zipf.write(full_path, os.path.relpath(full_path, REPO_PATH))
                # If the path is a directory, walk through and add all files within it
                elif os.path.isdir(full_path):
                    for root, _, files in os.walk(full_path):
                        if os.path.islink(root):
                            print(f"Skipping symlinked directory: '{root}'")
                            continue
                        for file in files:
                            file_path = os.path.join(root, file)
                            if not os.path.islink(file_path):
                                zipf.write(file_path, os.path.relpath(file_path, REPO_PATH))
                else:
                    print(f"Warning: Path '{path}' not found in the repository.")

        created_files.append(zip_path)

    return created_files

def check_for_compiler_errors(config):
    """Run a compilation check, send Telegram warnings/errors, and decide whether to block submission."""
    try:
        result = subprocess.run(["cargo", "check"], cwd=REPO_PATH, capture_output=True, text=True)
        
        # Check for errors
        if result.returncode != 0:
            message = f"❌ *Compiler Errors Detected*\n\n{result.stderr}"
            print(message)
            send_telegram_message(message)
            if not config.get("ALLOW_ERRORS", False):
                print("Errors not allowed. Blocking submission.")
                return False  # Block submission if errors are not allowed

        # Check for warnings
        if "warning" in result.stderr.lower():
            message = f"⚠️ *Compiler Warnings Detected*\n\n{result.stderr}"
            print(message)
            send_telegram_message(message)
            if not config.get("ALLOW_WARNINGS", False):
                print("Warnings not allowed. Blocking submission.")
                return False  # Block submission if warnings are not allowed

        print("✅ Compilation check completed. Warnings/errors allowed, proceeding with submission.")
        return True  # Continue submission
    except subprocess.CalledProcessError as e:
        message = f"❌ *Error Running Compilation Check*\n\n{str(e)}"
        print(message)
        send_telegram_message(message)
        return False

def submit_solution(zip_files, config, branch):
    """
    Submit multiple ZIP files via the OIOIOI API.
    The first ZIP file is submitted as "file", and subsequent ones as "file2", "file3", etc.
    """
    url = f"{OIOIOI_BASE_URL}/api/c/{config['contest_id']}/submit/{config['problem_short_name']}"
    headers = {
        "Authorization": f"token {OIOIOI_API_TOKEN}"
    }

    # Prepare files for submission
    files = {}
    for i, zip_file in enumerate(zip_files):
        file_key = "file" if i == 0 else f"file{i + 1}"  # Name the first file as "file"
        files[file_key] = (os.path.basename(zip_file), open(zip_file, 'rb'))

    # Submit the solution
    response = requests.post(url, headers=headers, files=files)

    # Close the opened file handles
    for file in files.values():
        file[1].close()

    if response.status_code == 200:
        submission_id = response.text.strip()
        message = (
            f"✅ *Submission Accepted*\n"
            f"• *Branch*: `{branch}`\n"
            f"• *Submission ID*: `{submission_id}`\n"
            f"• Waiting for results..."
        )
        print(message)
        send_telegram_message(message)
        return submission_id
    else:
        message = f"❌ *Submission Failed*\nStatus Code: {response.status_code}\nResponse: {response.text}"
        print(message)
        send_telegram_message(message)
        return None

def login_to_oioioi():
    """
    Log in to OIOIOI using the navbar login form.
    Fetches the CSRF token from the main page and performs the login.
    """
    main_page_url = f"{OIOIOI_BASE_URL}/"
    login_url = f"{OIOIOI_BASE_URL}/login/"
    session = requests.Session()

    # Step 1: Load the main page to fetch the CSRF token
    main_page = session.get(main_page_url, headers={"User-Agent": "Mozilla/5.0"})
    if main_page.status_code != 200:
        raise Exception(f"Failed to fetch the main page. Status code: {main_page.status_code}")

    # Parse the CSRF token
    soup = BeautifulSoup(main_page.content, "html.parser")
    csrf_token = soup.find("input", {"name": "csrfmiddlewaretoken"})
    csrf_token_value = csrf_token["value"] if csrf_token else None
    if not csrf_token_value:
        raise Exception("CSRF token not found on the main page.")

    # Step 2: Perform the login
    payload = {
        "csrfmiddlewaretoken": csrf_token_value,
        "auth-username": OIOIOI_USERNAME,
        "auth-password": OIOIOI_PASSWORD,
        "login_view-current_step": "auth",
    }
    headers = {
        "Referer": main_page_url,
        "Origin": OIOIOI_BASE_URL,
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "Mozilla/5.0",
    }

    response = session.post(login_url, data=payload, headers=headers)
    if response.status_code != 200 or "Log out" not in response.text:
        raise Exception(f"Login failed. Status code: {response.status_code}")

    return session

def parse_numeric_value(value):
    """
    Extract the numeric part from a string value.
    Removes non-numeric characters like 's' or spaces.
    """
    try:
        # Remove non-numeric characters except dots and slashes
        cleaned_value = re.sub(r"[^\d./]", "", value.strip())
        # Handle cases like "0.00 / 120.00"
        if "/" in cleaned_value:
            cleaned_value = cleaned_value.split("/")[0]
        return float(cleaned_value)
    except (ValueError, IndexError):
        return 0.0  # Return 0.0 if conversion fails

def fetch_test_results(session, contest_id, submission_id):
    """Fetch and parse the test results or error messages from the HTML report."""
    url = f"{OIOIOI_BASE_URL}/c/{contest_id}/get_report_HTML/{submission_id}/"
    try:
        response = session.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')

        # Check if the report contains a results table
        table = soup.select_one("table.table-report.submission")
        if not table:
            # If no table is present, check for error messages in the article
            article = soup.find("article")
            if article:
                error_message = article.find("p").text.strip() if article.find("p") else "Unknown error."
                additional_info = article.find("pre").text.strip() if article.find("pre") else ""
                return {"error": f"{error_message}\n{additional_info}".strip()}
            return None

        # Parse test results grouped by the first number in the test name
        rows = table.select('tbody tr')
        grouped_results = {}
        for row in rows:
            cells = row.find_all('td')
            if len(cells) > 1:
                test_name = cells[1].text.strip()
                result = cells[2].text.strip()
                runtime = parse_numeric_value(cells[3].text)  # Extract numeric runtime

                # Extract group key (first number from test name)
                group_key = test_name.split()[0][0]  # Extract the first number
                if group_key.isdigit():
                    group_key = int(group_key)
                else:
                    group_key = "Other"  # Catch-all for ungrouped tests

                # Add to grouped results
                if group_key not in grouped_results:
                    grouped_results[group_key] = {
                        "tests": [],
                        "total_score": 0.0
                    }

                grouped_results[group_key]["tests"].append({
                    "test_name": test_name,
                    "result": result,
                    "runtime": f"{runtime:.2f}s",  # Format runtime as a string
                })

                # Add to the total score for the group
                if len(cells) > 4:
                    score = parse_numeric_value(cells[4].text)  # Extract numeric score
                    grouped_results[group_key]["total_score"] += score

        return grouped_results
    except Exception as e:
        print(f"Error fetching or parsing results: {e}")
        return None


def format_results_message(grouped_results, results_url):
    """
    Format the grouped test results or error messages into structured Telegram messages.
    Splits into a header, per-group messages, and a summary with a link to the results.
    """

    if not grouped_results:
        return ["No results available yet."]

    if "error" in grouped_results:
        return [f"⚠️ *Error in test results*\n\n{grouped_results['error']}"]

    messages = []

    # Header with overall information
    total_score = sum(data["total_score"] for data in grouped_results.values())
    header = f"✅ *Test Results Overview*\n\n" \
             f"• Total Groups: {len(grouped_results)}\n" \
             f"• Overall Score: {total_score:.2f}\n\n" \
             f"📥 [View Full Results Here]({results_url})"
    messages.append(header)

    # Detailed results per group
    for group, data in sorted(grouped_results.items()):
        group_message = f"📂 *Group {group}*\n" \
                        f"• Total Group Score: {data['total_score']:.2f}\n\n"

        for test in data["tests"]:
            # Highlight successful tests in green and failed tests in red
            test_status = "🟢" if test["result"].lower() == "ok" else "⚪️" if test["result"].lower() == "skipped" else "🔴"

            # Ensure the runtime format is consistent (removing unnecessary newlines)
            runtime = test["runtime"].replace("\n", " ").strip()

            group_message += (
                f"{test_status} *{test['test_name']}* | ⏱ {runtime} | Result: {test['result']}\n"
            )

        if group_message:
            messages.append(group_message.strip())

    # Final summary with the link at the end
    summary = f"📊 *Final Summary*\n\n" \
              f"• Total Groups: {len(grouped_results)}\n" \
              f"• Overall Score: {total_score:.2f}\n\n" \
              f"📥 [View Full Results Here]({results_url})"
    messages.append(summary)

    return messages


def wait_for_results(session, contest_id, submission_id, check_interval=30):
    """Poll the results page periodically and send grouped results to Telegram."""
    while True:
        grouped_results = fetch_test_results(session, contest_id, submission_id)
        if grouped_results:
            results_url = f"{OIOIOI_BASE_URL}/c/{contest_id}/s/{submission_id}/"
            send_results_summary_to_telegram(contest_id, grouped_results, results_url)
            break
        else:
            print("Results not available yet. Checking again in a few seconds...")
            time.sleep(check_interval)


def compare_results(contest_id, grouped_results):
    """
    Compare current results with historical data and generate a detailed summary.
    Includes changes in solved tests, runtime improvements, and group-specific details.
    """
    history = load_submission_history()

    # Handle compilation or other errors
    if "error" in grouped_results:
        return f"❌ *Submission Failed*: {grouped_results['error']}"

    # Process normal test results
    current_successful = sum(
        1 for group in grouped_results.values() for test in group["tests"] if test["result"].lower() == "ok"
    )
    current_runtime = sum(
        parse_numeric_value(test["runtime"]) for group in grouped_results.values() for test in group["tests"]
    )

    summary = []
    test_group_changes = []

    if contest_id in history:
        prev_data = history[contest_id]
        prev_successful = prev_data["successful_tests"]
        prev_runtime = prev_data["total_runtime"]
        prev_group_results = prev_data.get("group_results", {})

        # Calculate overall improvements or regressions
        diff_successful = current_successful - prev_successful
        diff_runtime = current_runtime - prev_runtime

        if diff_successful > 0:
            summary.append(f"✅ *Improvement*: {diff_successful} more tests passed! 🎉")
        elif diff_successful < 0:
            summary.append(f"⚠️ *Regression*: {abs(diff_successful)} fewer tests passed.")
        else:
            summary.append(f"ℹ️ *No Changes*: The same number of tests passed.")

        summary.append(f"• *Total Successful Tests*: {current_successful}")
        summary.append(f"• *Runtime*: {'Faster' if diff_runtime < 0 else 'Slower'} by {abs(diff_runtime):.2f}s")

        # Compare the last solved test in each group
        for group, current_group_data in grouped_results.items():
            current_tests = current_group_data["tests"]
            last_solved_test = max(
                (test for test in current_tests if test["result"].lower() == "ok"),
                key=lambda x: x["test_name"],
                default=None
            )

            # Check if this group existed in the previous results
            if str(group) in prev_group_results:
                prev_last_solved_test = prev_group_results[str(group)]["last_solved_test"]

                # Check cases for improvement, regression, or no changes
                if last_solved_test and prev_last_solved_test:
                    if last_solved_test["test_name"] == prev_last_solved_test["test_name"]:
                        # Same last solved test: Compare runtime
                        prev_runtime = parse_numeric_value(prev_last_solved_test["runtime"])
                        current_runtime = parse_numeric_value(last_solved_test["runtime"])

                        if current_runtime < prev_runtime:
                            runtime_status = "🟢 Faster"
                        elif current_runtime > prev_runtime:
                            runtime_status = "🔴 Slower"
                        else:
                            runtime_status = "🟡 No Change"

                        test_group_changes.append(
                            f"🟡 Group {group}: Same last solved test `{last_solved_test['test_name']}`.\n"
                            f"   Runtime comparison: {runtime_status} ({prev_runtime:.2f}s → {current_runtime:.2f}s)"
                        )
                    elif last_solved_test["test_name"] > prev_last_solved_test["test_name"]:
                        test_group_changes.append(
                            f"🟢 Group {group}: Improved. "
                            f"Last solved test: `{prev_last_solved_test['test_name']}` → `{last_solved_test['test_name']}`"
                        )
                    else:
                        test_group_changes.append(
                            f"🔴 Group {group}: Regressed. "
                            f"Last solved test: `{prev_last_solved_test['test_name']}` → `{last_solved_test['test_name']}`"
                        )
                elif not last_solved_test and not prev_last_solved_test:
                    # No tests solved in either the current or previous submission
                    test_group_changes.append(
                        f"🟡 Group {group}: No Changes. No tests solved in either submission."
                    )
                elif last_solved_test:
                    # New tests solved in this submission but none previously
                    test_group_changes.append(
                        f"🟢 Group {group}: Improved. Last solved test: `{last_solved_test['test_name']}`"
                    )
                else:
                    # No tests solved in this submission but there were previously
                    test_group_changes.append(
                        f"🔴 Group {group}: Regressed. No tests solved in the latest submission."
                    )
            else:
                # No previous data for this group
                if last_solved_test:
                    test_group_changes.append(
                        f"🟢 Group {group}: New group solved. Last solved test: `{last_solved_test['test_name']}`"
                    )

    else:
        # No previous submission data exists
        summary.append(f"🆕 *First Submission*: {current_successful} tests passed.")
        test_group_changes.append("No comparison available since this is the first submission.")

    # Update history with the latest results
    updated_group_results = {
        str(group): {
            "last_solved_test": max(
                (test for test in data["tests"] if test["result"].lower() == "ok"),
                key=lambda x: x["test_name"],
                default=None
            )
        }
        for group, data in grouped_results.items()
    }

    history[contest_id] = {
        "successful_tests": current_successful,
        "total_runtime": current_runtime,
        "group_results": updated_group_results,
        "timestamp": time.time(),
    }
    save_submission_history(history)

    # Combine summary and group-specific changes
    comparison_message = "\n".join(summary)
    group_changes_message = "\n".join(test_group_changes)

    return f"{comparison_message}\n\n*Group Details:*\n{group_changes_message}"


def send_results_summary_to_telegram(contest_id, grouped_results, results_url):
    """Send a detailed summary of improvements and results via Telegram."""
    # Generate detailed results messages
    detailed_messages = format_results_message(grouped_results, results_url)
    
    # Generate improvement summary
    improvement_summary = compare_results(contest_id, grouped_results)
    summary_message = f"🚀 *Improvement Summary*:\n{improvement_summary}\n\n📥 [View Full Results Here]({results_url})"
    
    # Send detailed test results first
    for message in detailed_messages:
        send_telegram_message(message)

    # Send the improvement summary after detailed results
    send_telegram_message(summary_message)


def perform_auto_merge(branch):
    """
    Automatically merge the specified branch into PRIMARY_BRANCH after successful testing.
    Only performs the merge if there are no conflicts.
    """
    try:
        # Step 1: Checkout the PRIMARY_BRANCH branch
        subprocess.run(["git", "-C", REPO_PATH, "checkout", PRIMARY_BRANCH], check=True)

        # Step 2: Merge the target branch into PRIMARY_BRANCH with --no-commit and --no-ff to detect conflicts
        merge_result = subprocess.run(
            ["git", "-C", REPO_PATH, "merge", "--no-commit", "--no-ff", branch],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        # Check for conflicts
        if "CONFLICT" in merge_result.stderr:
            send_telegram_message(
                f"⚠️ *Merge Conflict Detected*\n"
                f"Branch `{branch}` could not be merged into `{PRIMARY_BRANCH}` due to conflicts.\n"
                f"Details:\n```\n{merge_result.stderr.strip()}\n```"
            )

            # Abort the merge
            subprocess.run(["git", "-C", REPO_PATH, "merge", "--abort"], check=True)
            return

        # Step 3: Commit and complete the merge if no conflicts
        subprocess.run(["git", "-C", REPO_PATH, "commit", "-m", f"Merge branch '{branch}' into `{PRIMARY_BRANCH}`"], check=True)

        # Step 4: Push the merged changes to the remote
        subprocess.run(["git", "-C", REPO_PATH, "push", "origin", PRIMARY_BRANCH], check=True)

        # Send Telegram notification about success
        send_telegram_message(f"✅ *Auto-Merge Successful*\n"
                              f"Branch `{branch}` was successfully merged into `{PRIMARY_BRANCH}`.")
    except subprocess.CalledProcessError as e:
        # Handle unexpected errors during merge and notify via Telegram
        send_telegram_message(f"❌ *Auto-Merge Failed*\n"
                              f"Error during merging branch `{branch}` into `{PRIMARY_BRANCH}`.\n"
                              f"Details: {str(e)}")


def main():
    global shutdown_flag
    global last_commit_per_branch

    session = login_to_oioioi()  # Login to OIOIOI and get a session
    print("Logged into OIOIOI successfully.")

    while not shutdown_flag:
        fetch_all_branches()

        # Check branches to track from the PRIMARY_BRANCH configuration
        branches_to_check = get_tracked_branches()

        for branch in branches_to_check:
            current_commit = get_latest_commit(branch)

            # Skip if the branch does not exist on the remote
            if current_commit is None:
                continue

            # Check if there's a new commit on this branch
            if branch not in last_commit_per_branch or current_commit != last_commit_per_branch[branch]:
                commit_message = subprocess.check_output(
                    ["git", "-C", REPO_PATH, "log", "-1", "--pretty=%B", current_commit]
                ).strip().decode('utf-8')

                message = (
                    f"🚨 *New Commit Detected*\n"
                    f"• *Branch*: `{branch}`\n"
                    f"• *Commit Hash*: `{current_commit}`\n"
                    f"• *Message*: {commit_message}\n"
                )
                print(message)
                send_telegram_message(message)

                # Load the config file from this specific commit
                config = load_config_from_commit(current_commit)

                # Skip if config is missing or AUTOCOMMIT is not enabled
                if not config or not config.get("AUTOCOMMIT", False):
                    message = (
                        f"⚠️ *Skipping Submission*\n"
                        f"• *Reason*: AUTOCOMMIT is disabled or config is missing.\n"
                        f"• *Branch*: `{branch}`\n"
                        f"• *Commit Hash*: `{current_commit}`"
                    )
                    print(message)
                    send_telegram_message(message)
                    last_commit_per_branch[branch] = current_commit
                    save_last_commits(last_commit_per_branch)
                    continue

                # Check for compiler errors and warnings
                if not check_for_compiler_errors(config):
                    message = (
                        f"❌ *Compilation Failed*\n"
                        f"• *Branch*: `{branch}`\n"
                        f"• *Commit Hash*: `{current_commit}`\n"
                        f"• *Warnings Allowed*: {config.get('ALLOW_WARNINGS', False)}\n"
                        f"• *Errors Allowed*: {config.get('ALLOW_ERRORS', False)}"
                    )
                    print(message)
                    send_telegram_message(message)
                    last_commit_per_branch[branch] = current_commit
                    save_last_commits(last_commit_per_branch)
                    continue

                # Create ZIP files based on include paths
                zip_files = create_zip_files(config)

                # Submit the solution and retrieve the submission ID
                submission_id = submit_solution(zip_files, config, branch)
                if submission_id:
                    wait_for_results(session, config["contest_id"], submission_id)

                    # Check if this branch should trigger an auto-merge
                    if branch == config.get("auto_merge_branch"):
                        grouped_results = fetch_test_results(session, config["contest_id"], submission_id)

                        # Ensure all tests passed before merging
                        if grouped_results and all(
                            test["result"].lower() == "ok"
                            for group in grouped_results.values()
                            for test in group["tests"]
                        ):
                            perform_auto_merge(branch)
                        else:
                            send_telegram_message(
                                f"⚠️ *Auto-Merge Skipped*\n"
                                f"Branch `{branch}` was not merged into `{PRIMARY_BRANCH}` due to test failures."
                            )

                # Clean up
                for zip_file in zip_files:
                    os.remove(zip_file)

                # Update the last processed commit for this branch and save to file
                last_commit_per_branch[branch] = current_commit
                save_last_commits(last_commit_per_branch)

        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    # Register signal handlers
    signal.signal(signal.SIGINT, handle_shutdown_signal)  # Ctrl+C
    signal.signal(signal.SIGTERM, handle_shutdown_signal)  # Termination signal

    print("Starting script. Press Ctrl+C to stop.")
    main()