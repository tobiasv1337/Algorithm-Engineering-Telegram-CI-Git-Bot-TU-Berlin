import re
import time
import os
import json

SUBMISSION_HISTORY_FILE = "data/submission_history.json"  # File to store submission history


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


def compare_results(chat_id, contest_id, grouped_results):
    """
    Compare current results with historical data and generate a detailed summary.
    Includes changes in solved tests, runtime improvements, and group-specific details.
    """
    history = load_submission_history(chat_id)  # Load submission history for the specific chat ID

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
            summary.append("ℹ️ *No Changes*: The same number of tests passed.")

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
    save_submission_history(chat_id, history)  # Save submission history for the specific chat ID

    # Combine summary and group-specific changes
    comparison_message = "\n".join(summary)
    group_changes_message = "\n".join(test_group_changes)

    return f"{comparison_message}\n\n*Group Details:*\n{group_changes_message}"


def send_results_summary_to_telegram(chat_id, contest_id, grouped_results, results_url, telegram_bot):
    """
    Send a detailed summary of improvements and results via Telegram for a specific chat ID.
    """
    # Generate detailed results messages
    detailed_messages = format_results_message(grouped_results, results_url)

    # Generate improvement summary
    improvement_summary = compare_results(chat_id, contest_id, grouped_results)
    summary_message = f"🚀 *Improvement Summary*:\n{improvement_summary}\n\n📥 [View Full Results Here]({results_url})"

    # Send detailed test results first
    for message in detailed_messages:
        telegram_bot.send_message(chat_id, message)

    # Send the improvement summary after detailed results
    telegram_bot.send_message(chat_id, summary_message)


def load_submission_history(chat_id):
    """Load historical submission data for a specific chat ID from a file."""
    if os.path.exists(SUBMISSION_HISTORY_FILE):
        with open(SUBMISSION_HISTORY_FILE, 'r') as f:
            all_histories = json.load(f)
        return all_histories.get(str(chat_id), {})
    return {}


def save_submission_history(chat_id, history):
    """Save historical submission data for a specific chat ID to the file."""
    if os.path.exists(SUBMISSION_HISTORY_FILE):
        with open(SUBMISSION_HISTORY_FILE, 'r') as f:
            all_histories = json.load(f)
    else:
        all_histories = {}

    all_histories[str(chat_id)] = history

    with open(SUBMISSION_HISTORY_FILE, 'w') as f:
        json.dump(all_histories, f, indent=4)
