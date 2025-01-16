import os
import tempfile
from zipfile import ZipFile
from config.config import Config

def create_zip_files(config):
    """
    Create multiple ZIP files based on the `zip_files` configuration in the submission config.
    Allows specifying destination paths for files and folders within the ZIP.
    Returns a list of created ZIP file paths and the temporary directory used.
    """
    zip_files = config.get("zip_files", [])
    temp_dir = tempfile.TemporaryDirectory()  # Create a temporary directory for ZIP files
    created_files = []

    for zip_config in zip_files:
        zip_name = zip_config.get("zip_name", "submission.zip")
        include_paths = zip_config.get("include_paths", [])
        zip_path = os.path.join(temp_dir.name, zip_name)  # Place ZIP files in the temp directory

        with ZipFile(zip_path, 'w') as zipf:
            for path_mapping in include_paths:
                source_path = os.path.join(Config.REPO_PATH, os.path.normpath(path_mapping["source"]))
                destination_path = os.path.normpath(path_mapping["destination"])

                # Verify that each path is within the repository and not a symlink
                if not source_path.startswith(Config.REPO_PATH) or os.path.islink(source_path):
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