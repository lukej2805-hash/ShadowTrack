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
import re
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
async def check_site(client, sem, site, username):
    url = site["url"].format(username)
    async with sem:
        try:
            r = await client.get(url, follow_redirects=True, timeout=10)
        except httpx.HTTPError:
            return {"site": site["name"], "url": url, "status": "error"}
    found = r.status_code == 200
    if found and site.get("error_text"):
        found = site["error_text"] not in r.text
    return {"site": site["name"], "url": url, "status": "found" if found else "not found"}


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
    for r in found:
        print(f"[+] {r['site']}: {r['url']}")
    errors = [r["site"] for r in results if r["status"] == "error"]
    print(f"\n{len(found)} found, {len(errors)} errored" + (f" ({', '.join(errors)})" if errors else ""))


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
