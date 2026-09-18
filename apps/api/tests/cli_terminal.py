"""Guarded POSIX-terminal test driver; secrets arrive only over stdin."""

import json
import os
import re
import select
import sys
import time

from sqlalchemy.engine import make_url


def main():
    # This helper is not an application command and can only touch the test DB.
    url = make_url(os.environ["DATABASE_URL"])
    if (
        os.environ.get("APP_ENV") != "test"
        or url.database != "technician_hub_test"
        or url.host not in {"127.0.0.1", "localhost", "test-db", "db"}
    ):
        raise SystemExit("Isolated test database required")
    import pty

    value = json.load(sys.stdin)
    password = value["password"]
    pid, fd = pty.fork()
    if pid == 0:
        os.execv(
            sys.executable,
            [
                sys.executable,
                "-m",
                "hub.auth.cli",
                "create-manager",
                "--username",
                value["username"],
            ],
        )
    captured = bytearray()
    prompts = 0
    status = None
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if select.select([fd], [], [], 0.1)[0]:
                try:
                    chunk = os.read(fd, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                captured.extend(chunk)
                if prompts == 0 and b"New manager password" in captured:
                    os.write(fd, (password + "\n").encode())
                    prompts = 1
                elif prompts == 1 and b"Confirm password:" in captured:
                    os.write(fd, (value.get("confirmation", password) + "\n").encode())
                    prompts = 2
            done, status = os.waitpid(pid, os.WNOHANG)
            if done:
                break
        else:
            raise SystemExit("CLI prompt timed out; output withheld")
    finally:
        os.close(fd)
        try:
            done, final = os.waitpid(pid, os.WNOHANG)
            if not done:
                # EOF may precede the exit notification by a few milliseconds.
                until = time.monotonic() + 2
                while not done and time.monotonic() < until:
                    time.sleep(0.01)
                    done, final = os.waitpid(pid, os.WNOHANG)
                if not done:
                    os.kill(pid, 9)
                    _, final = os.waitpid(pid, 0)
            status = final
        except ChildProcessError:
            pass
    if password.encode() in captured or b"$argon2" in captured or b"Traceback" in captured:
        raise SystemExit("CLI disclosed sensitive/internal output; output withheld")
    code = re.search(rb"\[([A-Z_]+)\]", captured)
    print(
        json.dumps(
            {
                "exit_code": os.waitstatus_to_exitcode(status),
                "prompts": prompts,
                "created": b"Manager created." in captured,
                "safe_code": code[1].decode() if code else None,
                "secret_echoed": False,
            }
        )
    )


if __name__ == "__main__":
    main()
