"""Acceptance: no secret in the built bundle. Reads the real credential values from dashboard/kite_config.json (if present)
and searches every built file for them, plus credential keywords. Prints only names and verdicts, never a value.
Usage: python3 fo-engine/tests/bundle-secrets.py <dist dir>"""
import json, pathlib, re, sys
dist = pathlib.Path(sys.argv[1])
repo = pathlib.Path(__file__).resolve().parents[4]
blob = b"".join(p.read_bytes() for p in dist.rglob("*") if p.is_file())
cfgp = repo / "dashboard" / "kite_config.json"
values = {}
if cfgp.exists():
    for k, v in json.loads(cfgp.read_text()).items():
        if isinstance(v, str) and len(v) >= 8 and re.search(r"token|secret|key|enc|pass", k, re.I):
            values[k] = v
bad = [k for k, v in values.items() if v.encode() in blob]
words = [w for w in ("access_token", "api_secret", "enctoken", "kite_config", "X-Kite-Version", "Authorization: token")
         if w.encode() in blob]
print(f"scanned {sum(1 for p in dist.rglob('*') if p.is_file())} files, {len(blob):,} bytes")
print(f"credential values from kite_config.json checked: {sorted(values)} -> found in bundle: {bad or 'none'}")
print(f"credential keywords found: {words or 'none'}")
sys.exit(1 if bad or words else 0)
