import os
import json
import tempfile
from zipfile import ZipFile

# Define the path for the central configuration file
CONFIG_FILE_PATH = "data/config.json"

# Ensure the data directory exists
os.makedirs(os.path.dirname(CONFIG_FILE_PATH), exist_ok=True)


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


# Centralized Configuration Management
def save_chat_config(chat_id, config_data):
    """
    Save configuration data for a specific chat ID.
    If the central JSON file does not exist, it will be created.
    """
    # Load existing data
    existing_data = get_all_chat_configs()

    # Update or add the chat-specific configuration
    existing_data[str(chat_id)] = existing_data.get(str(chat_id), {})
    existing_data[str(chat_id)].update(config_data)

    # Save the updated data back to the JSON file
    with open(CONFIG_FILE_PATH, "w") as file:
        json.dump(existing_data, file, indent=4)


def load_chat_config(chat_id):
    """
    Load configuration data for a specific chat ID.
    Returns None if no configuration exists for the given chat ID.
    """
    all_configs = get_all_chat_configs()
    return all_configs.get(str(chat_id), None)


def get_all_chat_configs():
    """
    Load all configurations from the central JSON file.
    Returns an empty dictionary if the file does not exist.
    """
    if not os.path.exists(CONFIG_FILE_PATH):
        return {}

    with open(CONFIG_FILE_PATH, "r") as file:
        return json.load(file)


def delete_chat_config(chat_id):
    """
    Delete configuration data for a specific chat ID.
    """
    all_configs = get_all_chat_configs()
    if str(chat_id) in all_configs:
        del all_configs[str(chat_id)]
        with open(CONFIG_FILE_PATH, "w") as file:
            json.dump(all_configs, file, indent=4)


def delete_old_auth_data(chat_id):
    """
    Delete old authentication data based on the previous authentication method.
    """
    current_config = load_chat_config(chat_id)
    auth_method = current_config.get("auth_method")
    chat_dir = get_chat_dir(chat_id)

    if auth_method == "ssh":
        # Remove SSH key files
        ssh_key_path = os.path.join(chat_dir, "id_rsa")
        ssh_key_pub_path = f"{ssh_key_path}.pub"
        if os.path.exists(ssh_key_path):
            os.remove(ssh_key_path)
        if os.path.exists(ssh_key_pub_path):
            os.remove(ssh_key_pub_path)
    elif auth_method == "https":
        # Clear Git username and password
        current_config.pop("git_username", None)
        current_config.pop("git_password", None)

    save_chat_config(chat_id, current_config)


def create_zip_files(config, chat_id):
    """
    Create multiple ZIP files based on the `zip_files` configuration provided.
    Allows specifying destination paths for files and folders within the ZIP.
    Returns a list of created ZIP file paths and the temporary directory used.

    Parameters:
        config (dict): Configuration dictionary containing "zip_files".
        chat_id (int or str): Chat ID to determine the repository path.
    """
    # Get the repository path using the chat ID
    repo_path = get_repo_path(chat_id)

    zip_files = config.get("zip_files", [])
    temp_dir = tempfile.TemporaryDirectory()  # Create a temporary directory for ZIP files
    created_files = []

    for zip_config in zip_files:
        zip_name = zip_config.get("zip_name", "submission.zip")
        include_paths = zip_config.get("include_paths", [])
        zip_path = os.path.join(temp_dir.name, zip_name)  # Place ZIP files in the temp directory

        with ZipFile(zip_path, 'w') as zipf:
            for path_mapping in include_paths:
                source_path = os.path.join(repo_path, os.path.normpath(path_mapping["source"]))
                destination_path = os.path.normpath(path_mapping["destination"])

                # Verify that each path is within the repository and not a symlink
                if not source_path.startswith(repo_path) or os.path.islink(source_path):
                    print(f"Skipping unsafe or invalid path: '{source_path}'")
                    continue

                # If the path is a file, add it directly to the specified destination
                if os.path.isfile(source_path):
                    zipf.write(source_path, destination_path)

                # If the path is a directory, walk through and add all files to the destination folder
                elif os.path.isdir(source_path):
                    for root, _, files in os.walk(source_path):
                        if os.path.islink(root):
                            print(f"Skipping symlinked directory: '{root}'")
                            continue
                        for file in files:
                            file_path = os.path.join(root, file)
                            if not os.path.islink(file_path):
                                # Compute the relative path to preserve folder structure
                                relative_path = os.path.relpath(file_path, source_path)
                                zipf.write(file_path, os.path.join(destination_path, relative_path))
                else:
                    print(f"Warning: Path '{source_path}' not found in the repository.")

        created_files.append(zip_path)

    return created_files, temp_dir
