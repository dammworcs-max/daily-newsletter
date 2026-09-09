"""
Daily brief: pulls unread Gmail, today's calendar events, and Notion
tasks/assignments, then asks Claude to summarize it all. Posts the
result as a GitHub Issue in this repo.
"""

import os
import imaplib
import email
from email.header import decode_header
import requests
import anthropic

def get_unread_emails():
    imap = imaplib.IMAP4_SSL("imap.gmail.com")
    imap.login(os.environ["GMAIL_ADDRESS"], os.environ["GMAIL_APP_PASSWORD"])
    imap.select("INBOX")
    _, data = imap.search(None, '(UNSEEN)')
    ids = data[0].split()[-15:]
    emails = []
    for eid in ids:
        _, msg_data = imap.fetch(eid, "(RFC822)")
        msg = email.message_from_bytes(msg_data[0][1])
        subject, enc = decode_header(msg["Subject"])[0]
        if isinstance(subject, bytes):
            subject = subject.decode(enc or "utf-8", errors="ignore")
        emails.append(f"From: {msg['From']} | Subject: {subject}")
    imap.logout()
    return "\n".join(emails) if emails else "No unread emails."


def get_calendar_events():
    url = os.environ["CALENDAR_ICAL_URL"]
    text = requests.get(url, timeout=15).text
    lines = text.splitlines()
    events = []
    current = {}
    for line in lines:
        if line.startswith("SUMMARY:"):
            current["summary"] = line[len("SUMMARY:"):]
        if line.startswith("DTSTART"):
            current["start"] = line.split(":")[-1]
        if line.startswith("END:VEVENT") and current:
            events.append(f"{current.get('start','?')}: {current.get('summary','?')}")
            current = {}
    return "\n".join(events[:20]) if events else "No events found in feed."


def query_notion_database(database_id):
    headers = {
        "Authorization": f"Bearer {os.environ['NOTION_TOKEN']}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }
    r = requests.post(
        f"https://api.notion.com/v1/databases/{database_id}/query",
        headers=headers, json={"page_size": 20}, timeout=15,
    )
    r.raise_for_status()
    rows = []
    for page in r.json().get("results", []):
        props = page.get("properties", {})
        rows.append(str({k: v.get(v.get("type"), "") for k, v in props.items()}))
    return "\n".join(rows) if rows else "Nothing found."


NOTION_TASKS_DB_ID = "31773cf86ab280f996bbf459005e4066"
NOTION_ASSIGNMENTS_DB_ID = "d0473cf86ab2824fac4f81b2d5197026"

def main():
    emails = get_unread_emails()
    events = get_calendar_events()
    tasks = query_notion_database(NOTION_TASKS_DB_ID)
    assignments = query_notion_database(NOTION_ASSIGNMENTS_DB_ID)

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    prompt = f"""Write a short, friendly daily brief from this raw data.
Skip anything that's just noise (promos, security alerts, newsletters).
Group into: Needs a reply, Today's schedule, Tasks, School.

EMAILS:
{emails}

CALENDAR:
{events}

TASKS:
{tasks}

ASSIGNMENTS:
{assignments}
"""
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}],
    )
    brief = response.content[0].text

    repo = os.environ["GITHUB_REPOSITORY"]
    gh_headers = {
        "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
        "Accept": "application/vnd.github+json",
    }
    requests.post(
        f"https://api.github.com/repos/{repo}/issues",
        headers=gh_headers,
        json={"title": "Daily Brief", "body": brief},
        timeout=15,
    )


if __name__ == "__main__":
    main()
