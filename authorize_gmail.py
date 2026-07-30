"""One-time Gmail authorization for the Receptionist agent.

Run this ONCE, on a machine with a browser, signed in as the mailbox owner
(assistant@vmedical.ca). It opens a Google consent screen, then writes
token.json (containing the refresh token) next to this script. After that the
agent authenticates silently — no further logins needed.

Usage:
    python authorize_gmail.py

Requires credentials.json (the OAuth client downloaded from Google Cloud
Console) in the same directory. See README for the console setup steps.
"""
from google_auth_oauthlib.flow import InstalledAppFlow

from receptionist.config import settings
from receptionist.gmail_client import SCOPES


def main() -> None:
    flow = InstalledAppFlow.from_client_secrets_file(
        settings.gmail_credentials_file, SCOPES
    )
    creds = flow.run_local_server(port=0, prompt="consent")
    with open(settings.gmail_token_file, "w") as f:
        f.write(creds.to_json())
    print(f"✓ Saved credentials to {settings.gmail_token_file}")
    print(f"  Authorized mailbox: {settings.gmail_address}")


if __name__ == "__main__":
    main()
