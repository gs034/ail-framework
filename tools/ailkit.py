#!/usr/bin/env python3
"""Local case notebook and narrow AIL API client. Python 3.8+; standard library only."""
import argparse
import datetime as dt
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import ssl
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid

MAX_FILE = 50 * 1024 * 1024
MAX_TEXT = 1024 * 1024


def die(message):
    raise ValueError(message)


def timestamp():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def case_path(raw):
    path = Path(raw).expanduser().resolve()
    if not (path / "case.json").is_file() or not (path / "evidence").is_dir():
        die("Not an ailkit case directory")
    return path


def log(path, action, **fields):
    line = json.dumps({"time_utc": timestamp(), "action": action, **fields},
                      sort_keys=True, ensure_ascii=False) + "\n"
    fd = os.open(str(path / "events.jsonl"), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as stream:
        stream.write(line)
        stream.flush()
        os.fsync(stream.fileno())


def events(path):
    with (path / "events.jsonl").open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def digest_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def init(args):
    path = Path(args.case).expanduser()
    path.mkdir(mode=0o700, parents=True, exist_ok=False)
    (path / "evidence").mkdir(mode=0o700)
    with (path / "case.json").open("x", encoding="utf-8") as stream:
        json.dump({"format": 1, "id": str(uuid.uuid4()), "title": args.title,
                   "created_utc": timestamp()}, stream, indent=2)
        stream.write("\n")
    if os.name != "nt":
        (path / "case.json").chmod(0o600)
    log(path, "case_created")
    print(path.resolve())


def add_file(args):
    path = case_path(args.case)
    source = Path(args.file).expanduser()
    if source.is_symlink() or not source.is_file():
        die("Input must be a regular file, not a symlink")
    if source.stat().st_size > MAX_FILE:
        die("Input exceeds 50 MiB")
    fd, temp_name = tempfile.mkstemp(prefix=".incoming-", dir=str(path / "evidence"))
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as out, source.open("rb") as stream:
            copied = 0
            while True:
                block = stream.read(1024 * 1024)
                if not block:
                    break
                copied += len(block)
                if copied > MAX_FILE:
                    die("Input grew beyond 50 MiB while copying")
                out.write(block)
            out.flush()
            os.fsync(out.fileno())
        if temp.stat().st_size > MAX_FILE:
            die("Input grew beyond 50 MiB while copying")
        digest = digest_file(temp)
        dest = path / "evidence" / digest
        if dest.exists():
            if dest.is_symlink() or digest_file(dest) != digest:
                die("Stored evidence failed verification")
            temp.unlink()
        else:
            os.replace(str(temp), str(dest))
            if os.name != "nt":
                dest.chmod(0o600)
        log(path, "file_added", sha256=digest, size_bytes=dest.stat().st_size,
            original_name=source.name, source=args.source or "")
        print(digest)
    finally:
        if temp.exists():
            temp.unlink()


def note(args):
    path = case_path(args.case)
    text = sys.stdin.read(MAX_TEXT + 1)
    if not text.strip() or len(text.encode("utf-8")) > MAX_TEXT:
        die("Supply 1 byte to 1 MiB of UTF-8 note text on stdin")
    log(path, "note_added", text=text, source=args.source or "")
    print("Note recorded")


def show(args):
    path = case_path(args.case)
    with (path / "case.json").open(encoding="utf-8") as stream:
        metadata = json.load(stream)
    print(json.dumps({"case": metadata, "events": events(path)}, indent=2, ensure_ascii=False))


def verify(args):
    path = case_path(args.case)
    digests = {entry["sha256"] for entry in events(path)
               if entry.get("action") == "file_added"}
    failures = []
    for digest in sorted(digests):
        blob = path / "evidence" / digest
        if blob.is_symlink() or not blob.is_file() or digest_file(blob) != digest:
            failures.append(digest)
    print(json.dumps({"checked": len(digests), "failed": failures}, indent=2))
    if failures:
        raise SystemExit(2)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        die("AIL redirected the API request; check the local tunnel")


def ail_origin(raw):
    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        die("AIL URL must be an HTTPS loopback origin without credentials")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        die("AIL URL must not contain a path, query, or fragment")
    if parsed.hostname != "localhost":
        try:
            loopback = ipaddress.ip_address(parsed.hostname).is_loopback
        except ValueError:
            loopback = False
        if not loopback:
            die("AIL URL must point to loopback")
    return raw.rstrip("/")


def ail_post(args, endpoint, payload):
    origin = ail_origin(args.ail_url)
    key = os.environ.get("AIL_API_KEY")
    if not key:
        die("Set AIL_API_KEY in the environment, not in a command argument")
    context = ssl.create_default_context(cafile=args.ca_cert)
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        urllib.request.HTTPSHandler(context=context),
        NoRedirect())
    request = urllib.request.Request(
        origin + endpoint, data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": key, "Content-Type": "application/json"},
        method="POST")
    try:
        with opener.open(request, timeout=15) as response:
            body = response.read(65537)
        if len(body) > 65536:
            die("AIL response exceeded 64 KiB")
        return json.loads(body)
    except urllib.error.HTTPError as error:
        die("AIL returned HTTP {}".format(error.code))
    except urllib.error.URLError as error:
        die("AIL connection or certificate validation failed: {}".format(error.reason))


def import_text(args):
    path = case_path(args.case)
    digest = args.sha256.lower()
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        die("Expected a SHA-256 digest from add-file")
    known = {entry.get("sha256") for entry in events(path)
             if entry.get("action") == "file_added"}
    if digest not in known:
        die("Digest is not recorded in this case")
    blob = path / "evidence" / digest
    if blob.is_symlink() or not blob.is_file() or digest_file(blob) != digest:
        die("Evidence failed verification")
    if blob.stat().st_size > MAX_TEXT:
        die("Text import is limited to 1 MiB")
    text = blob.read_text(encoding="utf-8")
    if not text.strip():
        die("Evidence contains no text")
    response = ail_post(args, "/api/v1/import/item", {"type": "text", "text": text})
    import_id = response.get("uuid")
    if not isinstance(import_id, str):
        die("AIL did not return an import UUID")
    log(path, "ail_import_submitted", sha256=digest, import_uuid=import_id)
    print(import_id)


def status(args):
    path = case_path(args.case)
    known = {entry.get("import_uuid") for entry in events(path)
             if entry.get("action") == "ail_import_submitted"}
    if args.uuid not in known:
        die("Import UUID is not recorded in this case")
    response = ail_post(args, "/api/v1/get/import/item", {"uuid": args.uuid})
    print(json.dumps(response, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("init", help="Create a case")
    p.add_argument("case")
    p.add_argument("--title", required=True)
    p.set_defaults(run=init)
    p = commands.add_parser("add-file", help="Quarantine and hash a local file")
    p.add_argument("case")
    p.add_argument("file")
    p.add_argument("--source", help="Source text or URL, recorded without fetching")
    p.set_defaults(run=add_file)
    p = commands.add_parser("note", help="Record UTF-8 text from stdin")
    p.add_argument("case")
    p.add_argument("--source")
    p.set_defaults(run=note)
    for name, handler in (("show", show), ("verify", verify)):
        p = commands.add_parser(name)
        p.add_argument("case")
        p.set_defaults(run=handler)
    for name, handler in (("import-text", import_text), ("status", status)):
        p = commands.add_parser(name, help="Use AIL's local text import API")
        p.add_argument("case")
        p.add_argument("sha256" if name == "import-text" else "uuid")
        p.add_argument("--ail-url", default="https://localhost:7000")
        p.add_argument("--ca-cert", help="CA certificate trusted for the AIL server")
        p.set_defaults(run=handler)
    args = parser.parse_args()
    try:
        args.run(args)
    except (ValueError, OSError, UnicodeError, json.JSONDecodeError) as error:
        print("Error: {}".format(error), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
