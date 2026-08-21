# Dashboard automation — daily Kite token & FII/DII refresh

Two launchd jobs keep the dashboard's live data current without daily manual work:

| Job | Script | When | Needs secrets? |
|-----|--------|------|----------------|
| `com.clade.kite-refresh` | `refresh_kite_token.py` | 08:00 daily | Yes (Keychain) |
| `com.clade.fii-dii-refresh` | `../live_fii_dii.py` | 18:30 Mon–Fri | No |

Both run on **this Mac** (they write local files and need a residential IP). They
run even when Claude / the terminal is closed, as long as you're logged in.

---

## 1. Kite token — one-time Keychain setup

Zerodha expires the access token daily; there is no permanent token. The job
logs in for you each morning using the **official Kite Connect** flow, generating
the 2FA code from your TOTP seed. It needs a paid Kite Connect subscription
(₹500/mo) and these five secrets, stored **once** in your macOS Keychain (nothing
is written to disk by this repo):

```bash
security add-generic-password -U -a kite -s kite-api-key     -w 'YOUR_API_KEY'
security add-generic-password -U -a kite -s kite-api-secret  -w 'YOUR_API_SECRET'
security add-generic-password -U -a kite -s kite-user-id     -w 'YOUR_ZERODHA_ID'   # e.g. AB1234
security add-generic-password -U -a kite -s kite-password    -w 'YOUR_PASSWORD'
security add-generic-password -U -a kite -s kite-totp-secret -w 'YOUR_TOTP_SEED'    # base32 seed
```

**Getting the TOTP seed:** in Kite → Profile → Settings → Password & Security →
"External TOTP" / re-enable TOTP. It shows a QR + a base32 secret (e.g.
`JBSWY3DPEHPK3PXP…`). Store that string — not the 6-digit code.

**Redirect URL:** in the [Kite developer console](https://developers.kite.trade/apps),
set the app's redirect URL to anything on `https://127.0.0.1` — the script reads
the `request_token` from the redirect, it does not need a running server there.

Verify the secrets are readable:

```bash
python3 dashboard/scripts/kite_secrets.py
```

Test the refresh once (writes a fresh token to `dashboard/kite_config.json`):

```bash
python3 dashboard/scripts/refresh_kite_token.py
```

## 2. FII/DII — no setup

Works out of the box. Test it (writes `dashboard/fii_dii_cache.json`):

```bash
python3 dashboard/live_fii_dii.py
```

## 3. Install & load the launchd jobs

```bash
cp dashboard/scripts/launchd/com.clade.kite-refresh.plist   ~/Library/LaunchAgents/
cp dashboard/scripts/launchd/com.clade.fii-dii-refresh.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.clade.kite-refresh.plist
launchctl load ~/Library/LaunchAgents/com.clade.fii-dii-refresh.plist
```

Check they're registered / run one now / read logs:

```bash
launchctl list | grep clade
launchctl start com.clade.fii-dii-refresh
tail dashboard/logs/*.log
```

To stop a job:

```bash
launchctl unload ~/Library/LaunchAgents/com.clade.kite-refresh.plist
```

> The plists hard-code the Python path
> (`/Library/Frameworks/Python.framework/Versions/3.13/bin/python3`) and the repo
> path. If you move the repo or change Python, update the plists and reload.

## Security notes

- Secrets live only in the macOS Keychain; `kite_secrets.py` reads them via the
  `security` CLI at runtime. `kite_config.json`, `fii_dii_cache.json`, and
  `logs/` are gitignored.
- The unofficial part is only the login *automation*; it uses Zerodha's own
  endpoints with your own credentials. If Zerodha changes the login flow, the
  morning job will log a clear error and the dashboard falls back to its last
  token / calibrated data.
