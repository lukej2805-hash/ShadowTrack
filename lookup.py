"""Find public accounts for a username, email or phone number.

Usage:
    python lookup.py johndoe
    python lookup.py john@example.com
    python lookup.py "+447700900123"
    python lookup.py johndoe --json
"""
import argparse
import asyncio
import hashlib
import json
import os
import random
import re
import string
import sys

import httpx
import phonenumbers
from phonenumbers import carrier, geocoder, timezone

HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
SITES_FILE = os.path.join(os.path.dirname(__file__), "sites.json")
MANUAL_FILE = os.path.join(os.path.dirname(__file__), "manual_sites.json")


def detect_type(value: str) -> str:
    if "@" in value and "." in value.split("@")[-1]:
        return "email"
    if re.fullmatch(r"\+?[\d\s\-().]{7,}", value):
        return "phone"
    return "username"


# ---------- username ----------
BLOCKED = {401, 403, 429, 999}
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)


def random_name():
    """A username that almost certainly doesn't exist, used as a control."""
    return "zx" + "".join(random.choices(string.ascii_lowercase + string.digits, k=12))


def norm(text, name):
    """Replace the username with a placeholder so pages can be compared."""
    return re.sub(re.escape(name), "{u}", text, flags=re.I)


def get_title(html, name):
    m = TITLE_RE.search(html)
    return norm(m.group(1).strip(), name).lower() if m else ""


async def fetch(client, sem, url):
    """GET with one retry on network errors, 429 and 5xx."""
    async with sem:
        for attempt in range(2):
            try:
                r = await client.get(url, follow_redirects=True, timeout=10)
            except httpx.HTTPError:
                if attempt == 1:
                    return None
                await asyncio.sleep(1)
                continue
            if r.status_code in (429, 500, 502, 503) and attempt == 0:
                await asyncio.sleep(1.5)
                continue
            return r
    return None


def compare(r, user, b, fake):
    """Compare the real-username page with the fake-username control page."""
    final = norm(str(r.url), user)
    # Both redirected to the same place that doesn't contain the username
    if r.history and b.history and final == norm(str(b.url), fake) and "{u}" not in final:
        return "not found"
    # Different page titles: the real one is a real page
    if get_title(r.text, user) != get_title(b.text, fake):
        return "found"
    # Same title and about the same size: site gives the same page for everyone
    fl, bl = len(r.text), len(b.text)
    if abs(fl - bl) <= 0.05 * max(fl, bl, 1):
        return "unverifiable"
    return "uncertain"


async def check_site(client, sem, site, username):
    url = site["url"].format(username)
    result = {"site": site["name"], "url": url}
    r = await fetch(client, sem, url)
    if r is None or r.status_code in BLOCKED or r.status_code >= 500:
        return {**result, "status": "error"}
    if r.status_code != 200:
        return {**result, "status": "not found"}

    # Explicit per-site rules win
    if site.get("error_text"):
        return {**result, "status": "not found" if site["error_text"] in r.text else "found"}
    if site.get("found_text"):
        return {**result, "status": "found" if site["found_text"] in r.text else "not found"}

    # Otherwise run a control check with a random username
    fake = random_name()
    b = await fetch(client, sem, site["url"].format(fake))
    if b is None or b.status_code in BLOCKED or b.status_code >= 500:
        return {**result, "status": "uncertain"}
    if b.status_code != 200:
        return {**result, "status": "found"}  # site 404s on missing users, so 200 is real
    return {**result, "status": compare(r, username, b, fake)}


async def search_username(username):
    with open(SITES_FILE, encoding="utf-8") as f:
        sites = json.load(f)
    sem = asyncio.Semaphore(10)
    async with httpx.AsyncClient(headers=HEADERS) as client:
        return await asyncio.gather(*(check_site(client, sem, s, username) for s in sites))


# ---------- email ----------
async def search_email(email):
    email = email.strip().lower()
    out = {"gravatar": None, "breaches": None}
    digest = hashlib.sha256(email.encode()).hexdigest()
    async with httpx.AsyncClient(headers=HEADERS) as client:
        try:
            r = await client.get(f"https://gravatar.com/{digest}.json", timeout=10)
            if r.status_code == 200:
                out["gravatar"] = f"https://gravatar.com/{digest}"
        except httpx.HTTPError:
            pass

        key = os.environ.get("HIBP_API_KEY")
        if key:
            try:
                r = await client.get(
                    f"https://haveibeenpwned.com/api/v3/breachedaccount/{email}",
                    headers={**HEADERS, "hibp-api-key": key},
                    params={"truncateResponse": "true"},
                    timeout=10,
                )
                if r.status_code == 200:
                    out["breaches"] = [b["Name"] for b in r.json()]
                elif r.status_code == 404:
                    out["breaches"] = []
            except httpx.HTTPError:
                pass

    # Try the part before the @ as a username too
    out["username_guess"] = email.split("@")[0]
    out["username_results"] = await search_username(out["username_guess"])
    return out


# ---------- phone ----------
def search_phone(raw, default_region="GB"):
    try:
        num = phonenumbers.parse(raw, default_region)
    except phonenumbers.NumberParseException as e:
        return {"error": str(e)}
    return {
        "valid": phonenumbers.is_valid_number(num),
        "international": phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.INTERNATIONAL),
        "region": geocoder.description_for_number(num, "en"),
        "carrier": carrier.name_for_number(num, "en") or "unknown",
        "timezones": list(timezone.time_zones_for_number(num)),
    }


# ---------- output ----------
def print_username(results):
    found = [r for r in results if r["status"] == "found"]
    unsure = [r for r in results if r["status"] in ("uncertain", "unverifiable")]
    errors = [r["site"] for r in results if r["status"] == "error"]
    for r in found:
        print(f"[+] {r['site']}: {r['url']}")
    if unsure:
        print("\nCouldn't verify automatically (open to check):")
        for r in unsure:
            print(f"[?] {r['site']}: {r['url']}")
    print(f"\n{len(found)} found, {len(unsure)} unverified, {len(errors)} errored"
          + (f" ({', '.join(errors)})" if errors else ""))


def print_manual(username):
    """Sites that block bots: print links for the user to open themselves."""
    with open(MANUAL_FILE, encoding="utf-8") as f:
        sites = json.load(f)
    print("\nCheck these manually (they block automated checks):")
    for site in sites:
        print(f"[?] {site['name']}: {site['url'].format(username)}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("query")
    p.add_argument("--json", action="store_true", help="print raw JSON")
    p.add_argument("--region", default="GB", help="default region for phone numbers")
    args = p.parse_args()

    kind = detect_type(args.query)
    if kind == "username":
        data = asyncio.run(search_username(args.query))
    elif kind == "email":
        data = asyncio.run(search_email(args.query))
    else:
        data = search_phone(args.query, args.region)

    if args.json:
        print(json.dumps(data, indent=2))
        return

    print(f"Type: {kind}\n")
    if kind == "username":
        print_username(data)
        print_manual(args.query)
    elif kind == "email":
        print("Gravatar:", data["gravatar"] or "none")
        if data["breaches"] is None:
            print("Breaches: skipped (set HIBP_API_KEY to enable)")
        else:
            print("Breaches:", ", ".join(data["breaches"]) or "none found")
        print(f"\nPossible accounts for username '{data['username_guess']}' (may be a different person):")
        print_username(data["username_results"])
        print_manual(data["username_guess"])
    else:
        for k, v in data.items():
            print(f"{k}: {v}")
        print("\nNote: phone numbers can only be parsed here, not matched to accounts.")


if __name__ == "__main__":
    main()
