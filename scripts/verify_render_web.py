"""Probe a built Render Web image with all runtime capabilities dropped.

Usage: python scripts/verify_render_web.py IMAGE
Uses only an isolated internal network and disposable tmpfs PostgreSQL.
"""

import argparse
import json
import subprocess
import time
from uuid import uuid4


def docker(*args, check=True):
    return subprocess.run(["docker", *args], check=check, text=True, capture_output=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image")
    args = parser.parse_args()
    prefix = "hub-render-check-" + uuid4().hex[:12]
    network, database, web = prefix, prefix + "-db", prefix + "-web"
    created = []
    docker("network", "create", "--internal", network)
    try:
        docker(
            "run",
            "-d",
            "--name",
            database,
            "--network",
            network,
            "--tmpfs",
            "/var/lib/postgresql",
            "-e",
            "POSTGRES_USER=hub",
            "-e",
            "POSTGRES_PASSWORD=isolated_" + prefix,
            "-e",
            "POSTGRES_DB=technician_hub_test",
            "postgres:18-alpine",
        )
        created.append(database)
        for _ in range(60):
            if (
                docker(
                    "exec",
                    database,
                    "pg_isready",
                    "-U",
                    "hub",
                    "-d",
                    "technician_hub_test",
                    check=False,
                ).returncode
                == 0
            ):
                break
            time.sleep(1)
        else:
            raise RuntimeError("Disposable PostgreSQL did not start")
        settings = {
            "RENDER": "true",
            "APP_ENV": "pilot",
            "APP_VERSION": "0.3.0",
            "RENDER_GIT_COMMIT": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], text=True
            ).strip(),
            "RENDER_DATABASE_URL": (
                f"postgresql://hub:isolated_{prefix}@{database}:5432/technician_hub_test"
            ),
            "PUBLIC_APP_ORIGIN": "https://pilot.example.test",
            "COOKIE_SECURE": "true",
            "DEBUG": "false",
            "ALLOW_FAKE_PROVIDERS": "false",
            "TELEGRAM_MODE": "disabled",
            "GOOGLE_MODE": "disabled",
            "SCHEDULE_DELIVERY_ENABLED": "false",
            "PORT": "10000",
        }
        options = ["--network", network, "--cap-drop=ALL"]
        for key, value in settings.items():
            options.extend(["-e", f"{key}={value}"])
        proof = docker(
            "run",
            "--rm",
            *options,
            args.image,
            "python",
            "-c",
            "import os,pwd,subprocess; assert pwd.getpwuid(os.geteuid()).pw_name=='hub'; "
            "assert os.access('/usr/bin/caddy',os.X_OK); "
            "assert 'security.capability' not in os.listxattr('/usr/bin/caddy'); "
            "subprocess.run(['caddy','version'],check=True); "
            "subprocess.run(['caddy','validate','--config','/app/render.Caddyfile',"
            "'--adapter','caddyfile'],check=True); print('hub / no file capabilities: PASS')",
        )
        print(proof.stdout.strip())
        docker("run", "--rm", *options, args.image, "python", "-m", "hub.render_runtime", "migrate")
        docker("run", "-d", "--name", web, "--memory=512m", "--cpus=0.5", *options, args.image)
        created.append(web)
        probe = (
            "import httpx; c=httpx.Client(base_url='http://127.0.0.1:10000'); "
            "r=c.get('/api/health'); assert r.status_code==200 and "
            "'application/json' in r.headers['content-type']; "
            "r=c.get('/login'); assert r.status_code==200 and '_next/' in r.text; "
            "assert c.get('/api/health',headers={'Host':'hostile.example',"
            "'X-Forwarded-Host':'pilot.example.test'}).status_code==400; "
            "print('single-port API / Next routing / Host protection: PASS')"
        )
        for _ in range(60):
            result = docker("exec", web, "python", "-c", probe, check=False)
            if result.returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError("Restricted Web routing failed: " + result.stderr)
        print(result.stdout.strip())
        logs = docker("logs", web).stdout
        for child in ("api", "next", "router"):
            assert f"Render process starting: {child}" in logs
        state = json.loads(docker("inspect", web).stdout)[0]
        assert state["Config"]["User"] == "hub"
        assert state["HostConfig"]["CapDrop"] == ["ALL"]
        assert not state["State"]["OOMKilled"]
        docker("stop", "--time=60", web)
        state = json.loads(docker("inspect", web).stdout)[0]
        assert state["State"]["ExitCode"] == 0
        print("three children / cap-drop=ALL / 512 MB / graceful shutdown: PASS")
    finally:
        for name in reversed(created):
            docker("rm", "-f", name, check=False)
        docker("network", "rm", network)


if __name__ == "__main__":
    main()
