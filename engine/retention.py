"""Retention (step 10): every file of a day older than the last N sessions is archived, the archive
copy is checksum-verified, and only then is the local file deleted (D-74: the data lives in the cloud,
not on the Mac). KEEP_LOCAL files stay because the engine reads past days' copies of them.

  python3 -m engine.retention [--dry-run]

Target (config retention.archive_target): a local path / external drive, s3://bucket/prefix (boto3,
AWS credentials from the environment), or gs://bucket/prefix (Google Cloud Storage through its
S3-compatible XML API, boto3 with an HMAC key: env GCS_HMAC_ACCESS_ID / GCS_HMAC_SECRET, else the
macOS Keychain items gcs-hmac-access-id / gcs-hmac-secret, account "engine").
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from .config import EngineConfig, load_config

DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# Read from past days: options.sqlite (IV history, chain_report.iv_history), trader_test.json (radar track record).
KEEP_LOCAL = {"options.sqlite", "trader_test.json", "trader_test.md", "archived.json"}
GCS_ENDPOINT = "https://storage.googleapis.com"


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class LocalTarget:
    def __init__(self, root: Path):
        self.root = Path(root).expanduser()

    def put(self, src: Path, rel: str) -> None:
        dst = self.root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)

    def sha256(self, rel: str) -> str | None:
        p = self.root / rel
        return sha256_file(p) if p.exists() else None


class S3Target:
    def __init__(self, url: str, client=None):
        bucket, _, prefix = url.split("://", 1)[1].partition("/")
        self.bucket, self.prefix = bucket, prefix.strip("/")
        if client is None:
            import boto3
            client = boto3.client("s3")
        self.s3 = client

    def _key(self, rel: str) -> str:
        return f"{self.prefix}/{rel}" if self.prefix else rel

    def put(self, src: Path, rel: str) -> None:
        self.s3.upload_file(str(src), self.bucket, self._key(rel))

    def sha256(self, rel: str) -> str | None:
        """Re-reads the stored object and hashes it (ETags are not content hashes for multipart uploads)."""
        try:
            body = self.s3.get_object(Bucket=self.bucket, Key=self._key(rel))["Body"]
        except Exception:
            return None
        h = hashlib.sha256()
        for chunk in iter(lambda: body.read(1 << 20), b""):
            h.update(chunk)
        return h.hexdigest()


def _secret(env: str, keychain: str) -> str | None:
    if os.environ.get(env):
        return os.environ[env]
    r = subprocess.run(["security", "find-generic-password", "-a", "engine", "-s", keychain, "-w"],
                       capture_output=True, text=True, timeout=10)
    return r.stdout.strip() if r.returncode == 0 else None


def gcs_client():
    """boto3 S3 client pointed at Google Cloud Storage with an HMAC key (never logged)."""
    import boto3
    from botocore.config import Config
    key, secret = _secret("GCS_HMAC_ACCESS_ID", "gcs-hmac-access-id"), _secret("GCS_HMAC_SECRET", "gcs-hmac-secret")
    if not (key and secret):
        raise RuntimeError("no GCS HMAC key: set GCS_HMAC_ACCESS_ID / GCS_HMAC_SECRET or the Keychain items "
                           "gcs-hmac-access-id / gcs-hmac-secret (account 'engine')")
    # GCS's XML API rejects the newer default flexible checksums of boto3 >= 1.36
    return boto3.client("s3", endpoint_url=GCS_ENDPOINT, aws_access_key_id=key, aws_secret_access_key=secret,
                        region_name="auto", config=Config(request_checksum_calculation="when_required",
                                                          response_checksum_validation="when_required"))


def make_target(spec: str):
    if spec.startswith("gs://"):
        return S3Target(spec, client=gcs_client())
    return S3Target(spec) if spec.startswith("s3://") else LocalTarget(Path(spec))


def day_files(day_dir: Path) -> list[Path]:
    return sorted(f for f in day_dir.rglob("*") if f.is_file() and f.relative_to(day_dir).as_posix() not in KEEP_LOCAL)


def archive_day(day_dir: Path, target, dry_run: bool = False) -> dict:
    """Archive + verify + delete each raw file of one day. Returns {rel: outcome}."""
    if (day_dir / "buffer.sqlite").exists():
        return {"_skipped": "not compacted yet (buffer.sqlite present): run engine.compact first"}
    out, manifest_p = {}, day_dir / "archived.json"
    manifest = json.loads(manifest_p.read_text()) if manifest_p.exists() else {}
    for f in day_files(day_dir):
        rel = f"{day_dir.name}/{f.relative_to(day_dir).as_posix()}"
        local = sha256_file(f)
        if dry_run:
            out[rel] = "would archive"
            continue
        try:
            target.put(f, rel)
            remote = target.sha256(rel)
        except Exception as e:  # any failure: keep the local file
            out[rel] = f"KEPT: archive failed ({e})"
            continue
        if remote != local:
            out[rel] = f"KEPT: checksum mismatch (local {local[:12]}, target {str(remote)[:12]})"
            continue
        manifest[rel] = {"sha256": local, "bytes": f.stat().st_size}
        manifest_p.write_text(json.dumps(manifest, indent=1, sort_keys=True))  # record before deleting
        f.unlink()
        out[rel] = "archived+verified+deleted"
    for sub in sorted((p for p in day_dir.rglob("*") if p.is_dir()), key=lambda p: -len(p.parts)):
        if not any(sub.iterdir()):
            sub.rmdir()
    return out


def run(cfg: EngineConfig, target=None, dry_run: bool = False) -> dict:
    keep = cfg.get("retention.raw_sessions_local")
    days = sorted(p for p in cfg.root.iterdir() if p.is_dir() and DAY.match(p.name)) if cfg.root.exists() else []
    target = target or make_target(cfg.get("retention.archive_target"))
    return {d.name: archive_day(d, target, dry_run) for d in days[:max(len(days) - keep, 0)]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="engine.retention")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--config", default=None)
    a = ap.parse_args(argv)
    res = run(load_config(a.config) if a.config else load_config(), dry_run=a.dry_run)
    print(json.dumps(res, indent=2))
    return 1 if any("KEPT" in str(v) for r in res.values() for v in r.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
