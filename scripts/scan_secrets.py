"""Scan Git-visible files; print only paths/rule names, never matching values."""

import re
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
files = (
    subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=root
    )
    .decode()
    .split("\0")
)
patterns = {
    "Google access token": re.compile(r"ya29\.[A-Za-z0-9_-]{20,}"),
    "Google OAuth client secret": re.compile(r"GOCSPX-[A-Za-z0-9_-]{20,}"),
    "Google refresh token": re.compile(r"1//[A-Za-z0-9_-]{30,}"),
    "Telegram bot credential": re.compile(r"(?<![\w])\d{6,12}:[A-Za-z0-9_-]{30,50}(?![\w])"),
    "Private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "Provider secret": re.compile(r"(?:sk-proj-|ghp_|github_pat_)[A-Za-z0-9_-]{30,}"),
    "Literal onboarding link": re.compile(
        r"https://t\.me/[A-Za-z0-9_]+\?start(?:group)?=[A-Za-z0-9_-]{43,}"
    ),
    "Literal session cookie": re.compile(r"hub_session=[A-Za-z0-9_-]{40,}"),
    "Literal Expense capability": re.compile(r"/technician/expense#[A-Za-z0-9_-]{43,}"),
    "Literal Work Report capability": re.compile(r"/technician/work-report#[A-Za-z0-9_-]{43,}"),
}
issues = []
count = 0
for name in sorted(set(files)):
    p = root / name
    if not name or not p.is_file():
        continue
    count += 1
    data = p.read_text(encoding="utf-8", errors="replace")
    for label, pattern in patterns.items():
        if pattern.search(data):
            issues.append(f"{name}: {label}")
if issues:
    raise SystemExit("Potential secrets found:\n" + "\n".join(issues))
print(f"Secret pattern scan passed: {count} Git-visible files; 0 findings.")
