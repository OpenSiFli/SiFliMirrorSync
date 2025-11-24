#!/usr/bin/env python3
import glob
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from subprocess import CalledProcessError


def log(msg: str) -> None:
    print(f"[cos-sync] {msg}")


def error(msg: str) -> None:
    print(f"::error::{msg}", file=sys.stderr)
    sys.exit(1)


def get_input(name: str, required: bool = True, default: str | None = None) -> str:
    env_name = f"INPUT_{name.upper()}"
    val = os.environ.get(env_name, "")
    if not val and default is not None:
        val = default
    if required and not val:
        error(f"Missing required input: {name}")
    return val


def parse_bool(val: str) -> bool:
    normalized = val.strip().lower()
    if normalized in ("true", "1", "yes", "y"):
        return True
    if normalized in ("false", "0", "no", "n", ""):
        return False
    error(f"Invalid boolean value for delete_remote: {val}")
    return False


def normalize_prefix(prefix: str) -> str:
    return prefix if prefix.endswith("/") else prefix + "/"


def split_patterns(raw: str) -> list[str]:
    parts = []
    for token in raw.split(","):
        for line in token.splitlines():
            cleaned = line.strip()
            if cleaned:
                parts.append(cleaned)
    return parts


def resolve_paths(patterns: list[str]) -> list[Path]:
    paths: list[Path] = []
    for pat in patterns:
        matches = [Path(p) for p in glob.glob(pat, recursive=True)]
        if not matches:
            error(f"No files matched pattern: {pat}")
        paths.extend(matches)
    return paths


def stage_paths(paths: list[Path], staging_root: Path) -> None:
    cwd = Path.cwd()
    for src in paths:
        abs_src = src.resolve()
        try:
            rel = abs_src.relative_to(cwd)
        except ValueError:
            error(f"Path must be within workspace: {abs_src}")
        dest = staging_root / rel

        if src.is_dir():
            if dest.exists() and dest.is_file():
                error(f"Collision while staging directory (file already staged here): {dest}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            log(f"Staging directory: {rel}")
            shutil.copytree(abs_src, dest, dirs_exist_ok=True)
        elif src.is_file():
            if dest.exists():
                if dest.is_file():
                    log(f"Skipping already staged file from overlapping glob: {rel}")
                    continue
                error(f"Collision while staging file (directory already staged here): {dest}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            log(f"Staging file: {rel}")
            shutil.copy2(abs_src, dest)
        else:
            error(f"Path is neither file nor directory: {src}")


def run_cmd(cmd: list[str], cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    log(f"Running: {' '.join(cmd)}" + (f" (cwd={cwd})" if cwd else ""))
    subprocess.run(cmd, check=True, cwd=str(cwd) if cwd else None, env=env)


def configure_coscmd(secret_id: str, secret_key: str, bucket: str, region: str, accelerate: bool = False) -> None:
    cmd = ["coscmd", "config", "-a", secret_id, "-s", secret_key, "-b", bucket]
    if accelerate:
        cmd += ["-e", "cos.accelerate.myqcloud.com"]
    else:
        cmd += ["-r", region]
    run_cmd(cmd)


def main() -> None:
    secret_id = get_input("secret_id")
    secret_key = get_input("secret_key")
    region = get_input("region")
    bucket = get_input("bucket")
    prefix = normalize_prefix(get_input("prefix"))
    artifacts_raw = get_input("artifacts")
    flush_url = get_input("flush_url", required=False, default="")
    delete_remote = parse_bool(get_input("delete_remote", required=False, default="false"))

    patterns = split_patterns(artifacts_raw)
    if not patterns:
        error("No artifact patterns provided after normalization")

    paths = resolve_paths(patterns)

    log("Configuring coscmd (regional endpoint)")
    configure_coscmd(secret_id, secret_key, bucket, region, accelerate=False)

    with tempfile.TemporaryDirectory() as tmpdir:
        staging_root = Path(tmpdir)
        log(f"Staging uploads in: {staging_root}")
        stage_paths(paths, staging_root)

        flags = ["-rs", "--yes"]
        if delete_remote:
            flags.append("--delete")

        try:
            run_cmd(
                ["coscmd", "upload", *flags, ".", prefix],
                cwd=staging_root,
            )
        except CalledProcessError:
            log("Upload failed with regional endpoint, retrying with global accelerate endpoint")
            configure_coscmd(secret_id, secret_key, bucket, region, accelerate=True)
            try:
                run_cmd(
                    ["coscmd", "upload", *flags, ".", prefix],
                    cwd=staging_root,
                )
            except CalledProcessError as exc:
                error(f"Upload failed after retry with accelerate endpoint: {exc}")

    if flush_url:
        log(f"Purge CDN cache: {flush_url}")
        env = os.environ.copy()
        env["TENCENTCLOUD_SECRET_ID"] = secret_id
        env["TENCENTCLOUD_SECRET_KEY"] = secret_key
        env["TENCENTCLOUD_REGION"] = region
        run_cmd(
            ["tccli", "cdn", "PurgePathCache", "--cli-unfold-argument", "--Paths", flush_url, "--FlushType", "flush"],
            env=env,
        )
    else:
        log("flush_url not provided; skipping CDN purge")


if __name__ == "__main__":
    main()
