import os
import time
import json
import signal
import subprocess
import requests
from zipfile import ZipFile
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configuration
CHECK_INTERVAL = 10  # Check every 10 seconds
REPO_PATH = "/home/contestbot/test"  # Set your repository path here
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

def send_telegram_message(message):
    """Send a message to the Telegram group."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    }
    try:
        response = requests.post(url, data=payload)
        if response.status_code == 200:
            print("Message sent to Telegram successfully.")
        else:
            print(f"Failed to send message to Telegram. Status code: {response.status_code}")
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

def create_zip_file(config):
    """Create a zip file with specified paths, ensuring all paths are within the repo."""
    zip_filename = "submission.zip"
    with ZipFile(zip_filename, 'w') as zipf:
        for path in config.get("include_paths", []):
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
    return zip_filename

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

def submit_solution(zip_filename, config):
    """Submit the solution via the OIOIOI API."""
    url = f"https://algeng.inet.tu-berlin.de/api/c/{config['contest']}/submit/{config['problem_short_name']}"
    headers = {
        "Authorization": f"token {OIOIOI_API_TOKEN}"
    }
    files = {'file': (zip_filename, open(zip_filename, 'rb')),
             'file2': (zip_filename, open(zip_filename, 'rb'))}
    
    response = requests.post(url, headers=headers, files=files)
    
    if response.status_code == 200:
        submission_id = response.text
        message = "Submission successful: " + submission_id
        print(message)
        send_telegram_message(message)
        return submission_id
    else:
        message = f"Submission failed: {response.status_code}\n{response.text}"
        print(message)
        send_telegram_message(message)
        return None

def main():
    global shutdown_flag
    global last_commit_per_branch

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
                message = f"New commit detected: {current_commit} on branch '{branch}'"
                print(message)
                send_telegram_message(message)

                # Load the config file from this specific commit
                config = load_config_from_commit(current_commit)
                
                # Skip if config is missing or AUTOCOMMIT is not enabled
                if not config or not config.get("AUTOCOMMIT", False):
                    message = "AUTOCOMMIT is disabled or config is missing. Skipping submission."
                    print(message)
                    send_telegram_message(message)
                    last_commit_per_branch[branch] = current_commit
                    save_last_commits(last_commit_per_branch)
                    continue

                # Check for compiler errors and warnings
                if not check_for_compiler_errors():
                    message = "Skipping submission due to compiler errors or warnings."
                    print(message)
                    send_telegram_message(message)
                    last_commit_per_branch[branch] = current_commit
                    save_last_commits(last_commit_per_branch)
                    continue

                # Create zip file based on include paths
                zip_filename = create_zip_file(config)
                
                # Submit the solution
                submit_solution(zip_filename, config)
                
                # Clean up
                os.remove(zip_filename)
                
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