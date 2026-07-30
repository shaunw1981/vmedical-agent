"""Fetch and print the most recent email from the agent inbox.

Use this to verify the Gmail connection and to grab a real transcript sample.
Run it after authorize_gmail.py and after a test call has landed an email.

Usage:
    python fetch_sample.py                 # newest message in the inbox
    python fetch_sample.py "from:ghl"      # newest message matching a query
"""
import sys

from receptionist.gmail_client import GmailClient


def main() -> None:
    query = sys.argv[1] if len(sys.argv) > 1 else ""
    client = GmailClient()
    msg = client.latest_message(query=query)
    if msg is None:
        print("No messages found" + (f" for query: {query!r}" if query else "") + ".")
        return

    print("=" * 70)
    print(f"From:    {msg.sender}")
    print(f"To:      {msg.to}")
    print(f"Date:    {msg.date}")
    print(f"Subject: {msg.subject}")
    print("=" * 70)
    print(msg.body_text or "(no plain-text body found)")
    print("=" * 70)


if __name__ == "__main__":
    main()
