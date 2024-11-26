import os
import time
import json
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
REPO_PATH = "/home/contestbot/test"  # Set your repository path here
OIOIOI_BASE_URL = "https://algeng.inet.tu-berlin.de"
OIOIOI_USERNAME = os.getenv("OIOIOI_USERNAME")
OIOIOI_PASSWORD = os.getenv("OIOIOI_PASSWORD")
OIOIOI_API_TOKEN = os.getenv("OIOIOI_API_TOKEN")  # Load API token from .env file
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
LAST_COMMITS_FILE = "last_commits.json"  # File to store last processed commit for each branch

# Global variable to track requested shutdown
shutdown_flag = False

# Graceful shutdown handler
def handle_shutdown_signal(signum, frame):
    global shutdown_flag
    print(f"\nSignal {signum} received. Shutting down gracefully...")
    shutdown_flag = True

# Load last processed commit hashes from file
def load_last_commits():
    """Load the last processed commit hashes from a file."""
    if os.path.exists(LAST_COMMITS_FILE):
        with open(LAST_COMMITS_FILE, 'r') as f:
            return json.load(f)
    return {}

# Save last processed commit hashes to file
def save_last_commits(last_commit_per_branch):
    """Save the last processed commit hashes to a file."""
    with open(LAST_COMMITS_FILE, 'w') as f:
        json.dump(last_commit_per_branch, f)

last_commit_per_branch = load_last_commits()  # Initialize with saved data if available

def send_telegram_message(message, parse_mode="Markdown", disable_web_page_preview=True):
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

    # Split message using the newline-aware function
    split_messages = split_message_by_newline(message, max_length)

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
    """Retrieve the list of branches to track from the last commit's configuration on main."""
    main_commit = get_latest_commit("main")
    if main_commit:
        config = load_config_from_commit(main_commit)
        if config and "branches" in config:
            return config["branches"]
    return ["main"]  # Default to main if branches are not specified

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

def check_for_compiler_errors():
    """Run a compilation check and return True if there are no errors or warnings."""
    try:
        result = subprocess.run(["cargo", "check"], cwd=REPO_PATH, capture_output=True, text=True)
        
        if result.returncode != 0:
            message = f"Compiler error or warning detected:\n{result.stderr}"
            print(message)
            send_telegram_message(message)
            return False  # Compilation failed with errors or warnings

        if "warning" in result.stderr.lower():
            message = f"Warning detected during compilation:\n{result.stderr}"
            print(message)
            send_telegram_message(message)
            return False  # Warnings found

        print("No compiler errors or warnings detected.")
        return True  # Compilation successful with no warnings
    except subprocess.CalledProcessError as e:
        message = f"Error running compilation check: {e}"
        print(message)
        send_telegram_message(message)
        return False

def submit_solution(zip_files, config):
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
            f"• *Branch*: `{config['branches']}`\n"
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
                runtime = cells[3].text.strip()
                score = cells[4].text.strip() if len(cells) > 4 else "0.0"

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
                    "runtime": runtime,
                    "score": score
                })

                # Add to the total score for the group
                try:
                    grouped_results[group_key]["total_score"] += float(score.split()[0])
                except ValueError:
                    pass  # Skip invalid score entries

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
            test_status = "🟢" if test["result"].lower() == "ok" else "🔴"

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


def wait_for_results(session, contest_id, submission_id, check_interval=10):
    """
    Poll the results page periodically and send structured results to Telegram.
    Splits messages into header, per-group details, and a summary, with a link in the last message.
    """
    results_url = f"{OIOIOI_BASE_URL}/c/{contest_id}/s/{submission_id}/"

    while True:
        grouped_results = fetch_test_results(session, contest_id, submission_id)
        if grouped_results:
            # Format and send results
            messages = format_results_message(grouped_results, results_url)

            for msg in messages:
                send_telegram_message(msg)
            break
        else:
            print("Results not available yet. Checking again in a few seconds...")
            time.sleep(check_interval)

def main():
    global shutdown_flag
    global last_commit_per_branch

    session = login_to_oioioi()  # Login to OIOIOI and get a session
    print("Logged into OIOIOI successfully.")

    while not shutdown_flag:
        fetch_all_branches()

        # Check branches to track from the main branch configuration
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
                if not check_for_compiler_errors():
                    message = (
                        f"❌ *Compilation Failed*\n"
                        f"• *Branch*: `{branch}`\n"
                        f"• *Commit Hash*: `{current_commit}`"
                    )
                    print(message)
                    send_telegram_message(message)
                    last_commit_per_branch[branch] = current_commit
                    save_last_commits(last_commit_per_branch)
                    continue

                # Create ZIP files based on include paths
                zip_files = create_zip_files(config)

                # Submit the solution and retrieve the submission ID
                submission_id = submit_solution(zip_files, config)
                if submission_id:
                    wait_for_results(session, config["contest_id"], submission_id)

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