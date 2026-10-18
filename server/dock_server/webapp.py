"""Dock's phone app at a fixed address, so it can be installed once and the
link never changes.

The free Cloudflare tunnel gets a new address each time Dock starts (and
sometimes after the Mac sleeps). So Dock also puts the phone app's files in a
small Amazon S3 bucket in your AWS account:

    https://<bucket>.s3.<region>.amazonaws.com/index.html   (never changes)

Next to them, address.json holds the tunnel's current address. The installed
app reads it each time it connects, so it finds the Mac by itself.

What is public: only the phone app's own files (the same as in the repo) and
the tunnel's address. The pairing token is never uploaded: the QR code passes
it after "#", which browsers keep on the phone, and the app then remembers it.

The bucket is created on the first run and its name kept in
.data/webapp.json. Set DOCK_WEBAPP=off to skip all of this; the phone then
uses the tunnel address directly, as before.
"""

import json
import mimetypes
import os
import secrets
import threading
import time
from pathlib import Path

import boto3

from dock_server import tunnel
from dock_server.state import DATA_DIR

SETTINGS_FILE = DATA_DIR / "webapp.json"
NOT_UPLOADED = {"setup.html"}  # the Mac's setup page stays on the Mac
mimetypes.add_type("application/manifest+json", ".webmanifest")
mimetypes.add_type("text/javascript", ".js")

_base = ""      # https://<bucket>.s3.<region>.amazonaws.com once the files are up
_problem = ""


def app_url() -> str:
    return f"{_base}/index.html" if _base else ""


def origin() -> str:
    """The app's web address, which may call this server (see main.py)."""
    return _base


def problem() -> str:
    return _problem


def start(static_dir: Path) -> None:
    if os.environ.get("DOCK_WEBAPP", "").lower() in ("off", "0", "no") or os.environ.get("DOCK_PUBLIC_URL"):
        return  # a fixed address of its own needs none of this
    threading.Thread(target=_run, args=(static_dir,), daemon=True).start()


def _run(static_dir: Path) -> None:
    global _base, _problem
    while True:  # (e.g. the AWS login expired: try again until it's back)
        try:
            s3 = boto3.client("s3")
            bucket, region = _bucket(s3)
            _upload_app(s3, bucket, static_dir)
            _base = f"https://{bucket}.s3.{region}.amazonaws.com"
            _problem = ""
            print(f"Phone app (fixed address): {app_url()}")
            break
        except Exception as e:
            if not _problem:
                print(f"Couldn't set up the fixed phone app address on AWS S3 yet: {str(e)[:200]}")
            _problem = f"Couldn't reach AWS S3 for the fixed phone address: {str(e)[:200]}"
            time.sleep(30)
    published = None
    uploaded = _changed_at(static_dir)
    while True:  # keep address.json pointing at the tunnel's current address
        if _changed_at(static_dir) != uploaded:  # the app's files were edited: upload them again
            uploaded = _changed_at(static_dir)
            try:
                _upload_app(s3, bucket, static_dir)
                print("Updated the phone app's files.")
            except Exception as e:
                print(f"Couldn't update the phone app's files: {e!r}")
        url = tunnel.public_url()
        if url and url != published:
            try:
                s3.put_object(Bucket=bucket, Key="address.json", Body=json.dumps({"url": url}),
                              ContentType="application/json", CacheControl="no-store")
                published = url
                print(f"Told the phone app the new Mac address: {url}")
            except Exception as e:
                print(f"Couldn't update the phone app's address: {e!r}")
        time.sleep(3)


def _bucket(s3) -> tuple[str, str]:
    """The bucket for the app, made on the first run: public to read, nothing else."""
    settings = json.loads(SETTINGS_FILE.read_text()) if SETTINGS_FILE.exists() else {}
    if settings.get("bucket"):
        return settings["bucket"], settings["region"]
    region = s3.meta.region_name or "us-east-1"
    bucket = f"dock-app-{secrets.token_hex(6)}"
    extra = {} if region == "us-east-1" else {"CreateBucketConfiguration": {"LocationConstraint": region}}
    s3.create_bucket(Bucket=bucket, **extra)
    # Allow a "anyone can read" policy on this bucket only (no public ACLs).
    s3.put_public_access_block(Bucket=bucket, PublicAccessBlockConfiguration={
        "BlockPublicAcls": True, "IgnorePublicAcls": True, "BlockPublicPolicy": False, "RestrictPublicBuckets": False})
    s3.put_bucket_policy(Bucket=bucket, Policy=json.dumps({
        "Version": "2012-10-17",
        "Statement": [{"Sid": "ReadDockApp", "Effect": "Allow", "Principal": "*",
                       "Action": "s3:GetObject", "Resource": f"arn:aws:s3:::{bucket}/*"}],
    }))
    DATA_DIR.mkdir(exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps({"bucket": bucket, "region": region}, indent=2))
    print(f"Made the S3 bucket {bucket} for the phone app.")
    return bucket, region


def _changed_at(static_dir: Path) -> float:
    return max((p.stat().st_mtime for p in static_dir.iterdir() if p.is_file()), default=0)


def _upload_app(s3, bucket: str, static_dir: Path) -> None:
    for path in sorted(static_dir.iterdir()):
        if not path.is_file() or path.name in NOT_UPLOADED or path.name.startswith("."):
            continue
        body = path.read_bytes()
        if path.name == "config.js":
            body = b'// The installed app: read where the Mac is from address.json.\nwindow.DOCK_ADDRESS_URL = "address.json";\n'
        s3.put_object(Bucket=bucket, Key=path.name, Body=body, CacheControl="no-cache",
                      ContentType=mimetypes.guess_type(path.name)[0] or "application/octet-stream")
