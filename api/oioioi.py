import requests
import os
import time
from bs4 import BeautifulSoup
from config.config import Config
from utils.results_utils import (parse_numeric_value, send_results_summary_to_telegram)
from file_operations import load_chat_config


class OioioiAPI:
    def __init__(self, chat_id):
        """
        Initialize OioioiAPI with user-specific credentials based on chat_id.
        """
        self.chat_id = chat_id
        self.base_url = Config.OIOIOI_BASE_URL

        # Load user-specific credentials
        config = load_chat_config(chat_id)
        if not config:
            raise ValueError(f"No configuration found for chat ID {chat_id}")

        self.username = config.get("oioioi_username")
        self.password = config.get("oioioi_password")
        self.api_keys = config.get("OIOIOI_API_KEYS", {})
        self.session = requests.Session()

    def get_api_key_for_contest(self, contest_id):
        """
        Retrieve the API key for a specific contest ID.
        Raises an exception if no API key is found for the contest.
        """
        api_key = self.api_keys.get(contest_id)
        if not api_key:
            raise KeyError(f"❌ No API key found for contest '{contest_id}'. Use /update to add it.")
        return api_key

    def login(self):
        """
        Log in to OIOIOI using the navbar login form.
        Fetches the CSRF token from the main page and performs the login.
        """
        main_page_url = f"{self.base_url}/"
        login_url = f"{self.base_url}/login/"
        self.session = requests.Session()

        # Load the main page to fetch the CSRF token
        main_page = self.session.get(main_page_url, headers={"User-Agent": "Mozilla/5.0"})
        if main_page.status_code != 200:
            raise Exception(f"Failed to fetch the main page. Status code: {main_page.status_code}")

        # Parse the CSRF token
        soup = BeautifulSoup(main_page.content, "html.parser")
        csrf_token = soup.find("input", {"name": "csrfmiddlewaretoken"})
        csrf_token_value = csrf_token["value"] if csrf_token else None
        if not csrf_token_value:
            raise Exception("CSRF token not found on the main page.")

        # Perform the login
        payload = {
            "csrfmiddlewaretoken": csrf_token_value,
            "auth-username": self.username,
            "auth-password": self.password,
            "login_view-current_step": "auth",
        }
        headers = {
            "Referer": main_page_url,
            "Origin": self.base_url,
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "Mozilla/5.0",
        }

        response = self.session.post(login_url, data=payload, headers=headers)
        if response.status_code != 200 or "Log out" not in response.text:
            raise Exception(f"Login failed. Status code: {response.status_code}")

    def submit_solution(self, contest_id, problem_short_name, zip_files, branch, telegram_bot):
        """
        Submit multiple ZIP files via the OIOIOI API for the specified contest.
        The first ZIP file is submitted as "file", and subsequent ones as "file2", "file3", etc.
        """
        try:
            api_key = self.get_api_key_for_contest(contest_id)
        except KeyError:
            message = (
                f"❌ *Submission Aborted*\n"
                f"No API key found for contest '{contest_id}'.\n"
                f"Please add the API key to continue."
            )
            print(message)
            telegram_bot.send_message(message)
            return None

        url = f"{self.base_url}/api/c/{contest_id}/submit/{problem_short_name}"
        headers = {"Authorization": f"token {api_key}"}

        # Prepare files for submission
        files = {}
        for i, zip_file in enumerate(zip_files):
            file_key = "file" if i == 0 else f"file{i + 1}"  # Name the first file as "file"
            files[file_key] = (os.path.basename(zip_file), open(zip_file, 'rb'))

        # Submit the solution
        try:
            response = self.session.post(url, headers=headers, files=files)

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
                telegram_bot.send_message(message)
                return submission_id
            else:
                message = f"❌ *Submission Failed*\nStatus Code: {response.status_code}\nResponse: {response.text}"
                print(message)
                telegram_bot.send_message(message)
                return None
        except Exception as e:
            message = f"❌ *Submission Failed*\nError: {str(e)}"
            print(message)
            telegram_bot.send_message(message)
            return None

    def get_results_url(self, contest_id, submission_id):
        """
        Generate the results URL for a specific contest and submission ID.
        """
        return f"{self.base_url}/c/{contest_id}/s/{submission_id}/"

    def fetch_test_results(self, contest_id, submission_id):
        """
        Fetch and parse the test results or error messages from the HTML report.
        """
        url = f"{self.base_url}/c/{contest_id}/get_report_HTML/{submission_id}/"
        try:
            response = self.session.get(url)
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
                    runtime = parse_numeric_value(cells[3].text)

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
                        score = parse_numeric_value(cells[4].text)
                        grouped_results[group_key]["total_score"] += score

            return grouped_results
        except Exception as e:
            print(f"Error fetching or parsing results: {e}")
            return None

    def wait_for_results(self, contest_id, submission_id, telegram_bot):
        """
        Poll the results page periodically and send grouped results to Telegram.
        """
        while True:
            grouped_results = self.fetch_test_results(contest_id, submission_id)
            if grouped_results:
                results_url = self.get_results_url(contest_id, submission_id)
                send_results_summary_to_telegram(contest_id, grouped_results, results_url, telegram_bot)
                break
            else:
                print("Results not available yet. Checking again in a few seconds...")
                time.sleep(Config.CHECK_INTERVAL)
