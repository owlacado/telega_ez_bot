"""Only this explicit managed section is owned by Hub; all outside text is opaque."""

import re
from datetime import UTC

START = "[TECHNICIAN HUB REPORT]"
END = "[/TECHNICIAN HUB REPORT]"

BLOCK = re.compile(re.escape(START) + r".*?" + re.escape(END), re.S)


def safe(value):
    return str(value).replace(START, "[Hub report marker]").replace(END, "[/Hub report marker]")


def render(revision):
    payment = revision.payment_method.replace("_", " ").title()
    closer = revision.closed_by.replace("_", " ").title()
    return "\n".join(
        [
            START,
            f"Submitted: {revision.submitted_at.astimezone(UTC):%Y-%m-%d %H:%M:%S UTC}",
            f"Technician: {safe(revision.technician_name)}",
            f"Amount of closed project: ${revision.amount_closed:.2f}",
            f"Type of payment: {payment}",
            f"Who closed this project?: {closer}",
            f"Job description & comments: {safe(revision.comments)}",
            f"Groupon review: {revision.groupon_reviews}",
            f"Google review: {revision.google_reviews}",
            f"Facebook review: {revision.facebook_reviews}",
            "Yearly maintenance plan was provided: "
            + ("Yes" if revision.yearly_maintenance_plan_provided else "No"),
            END,
        ]
    )


def merge(description, block):
    # Refuse malformed/nested sections instead of guessing which manual text to remove.
    matches = list(BLOCK.finditer(description))
    if (
        description.count(START) != len(matches)
        or description.count(END) != len(matches)
        or any(START in m.group()[len(START) :] for m in matches)
    ):
        raise ValueError("MANAGED_BLOCK_MALFORMED")
    if not matches:
        return description + ("\n\n" if description else "") + block
    parts, cursor = [], 0
    for index, match in enumerate(matches):
        parts.extend([description[cursor : match.start()], block if index == 0 else ""])
        cursor = match.end()
    parts.append(description[cursor:])
    return "".join(parts)
