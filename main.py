import os
import time
import json
import subprocess
import requests
from zipfile import ZipFile
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configuration
CHECK_INTERVAL = 10  # Check every 10 seconds
REPO_PATH = "/home/contestbot/test"  # Set your repository path here
API_TOKEN = os.getenv("API_TOKEN")  # Load API token from .env file
LAST_COMMITS_FILE = "last_commits.json"  # File to store last processed commit for each branch

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

def fetch_all_branches():
    """Fetch all branches from the remote repository and handle fetch errors."""
    try:
        subprocess.run(["git", "-C", REPO_PATH, "fetch", "--all"], check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error fetching branches: {e}")
        print("Retrying fetch on next iteration...")

def get_latest_commit(branch):
    """Get the latest commit hash on the specified branch. Return None if the branch does not exist."""
    try:
        return subprocess.check_output(["git", "-C", REPO_PATH, "rev-parse", f"origin/{branch}"]).strip().decode('utf-8')
    except subprocess.CalledProcessError:
        print(f"Warning: Branch '{branch}' does not exist on the remote. Skipping.")
        return None

def load_config_from_commit(commit_hash):
    """Load submission configuration from a specific commit."""
    try:
        config_data = subprocess.check_output(["git", "-C", REPO_PATH, "show", f"{commit_hash}:submission_config.json"])
        return json.loads(config_data)
    except subprocess.CalledProcessError:
        print(f"Configuration file 'submission_config.json' not found in commit {commit_hash}.")
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

def submit_solution(zip_filename, config):
    """Submit the solution via the OIOIOI API."""
    url = f"https://algeng.inet.tu-berlin.de/api/c/{config['contest']}/submit/{config['problem_short_name']}"
    headers = {
        "Authorization": f"token {API_TOKEN}"
    }
    files = {'file': (zip_filename, open(zip_filename, 'rb'))}
    
    response = requests.post(url, headers=headers, files=files)
    
    if response.status_code == 200:
        print("Submission successful:", response.json())
    else:
        print("Submission failed:", response.status_code, response.text)

def main():
    global last_commit_per_branch

    while True:
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
                print(f"New commit detected: {current_commit} on branch '{branch}'")

                # Load the config file from this specific commit
                config = load_config_from_commit(current_commit)
                
                # Skip if config is missing or AUTOCOMMIT is not enabled
                if not config or not config.get("AUTOCOMMIT", False):
                    print("AUTOCOMMIT is disabled or config is missing.")
                    last_commit_per_branch[branch] = current_commit
                    save_last_commits(last_commit_per_branch)  # Persist the last commits
                    continue

                # Create zip file based on include paths
                zip_filename = create_zip_file(config)
                
                # Submit the solution
                submit_solution(zip_filename, config)
                
                # Clean up
                os.remove(zip_filename)
                
                # Update the last processed commit for this branch and save to file
                last_commit_per_branch[branch] = current_commit
                save_last_commits(last_commit_per_branch)  # Persist the last commits

        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()