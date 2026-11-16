# ShadowTrack

**ShadowTrack** is a command-line tool that checks where a username, email address, or phone number shows up online and lists links to any publicly visible accounts. Give it a username and it searches dozens of sites at once. Give it an email and it looks for a Gravatar profile, checks for known data breaches (with a Have I Been Pwned API key), and searches the part before the @ as a possible username. Give it a phone number and it validates it and shows the region, carrier, and timezone. Some sites block automated checks, so the tool prints links for those to open yourself. ShadowTrack is meant for checking your own online footprint or for consented research. Please don't use it to harass, stalk, or dox anyone.

## Requirements
- Python 3.8 or newer

## Setup
Clone the repo (or tap **Code** → **Download ZIP** on GitHub and unzip it), then install the dependencies:

    git clone https://github.com/YOUR-USERNAME/shadowtrack.git
    cd shadowtrack
    pip install -r requirements.txt

On Windows you may need `py` instead of `python`. On Mac/Linux you may need `python3` and `pip3`.

## Usage
    python lookup.py johndoe
    python lookup.py john@example.com
    python lookup.py "+447700900123"

Options:

    --json            print raw JSON instead of readable text
    --region GB       default country for phone numbers without a + prefix

### Example output
    $ python lookup.py johndoe

    Type: username

    [+] GitHub: https://github.com/johndoe
    [+] Reddit: https://www.reddit.com/user/johndoe/about.json
    [+] Dev.to: https://dev.to/johndoe

    3 found, 0 errored

    Check these manually (they block automated checks):
    [?] Instagram: https://www.instagram.com/johndoe/
    [?] TikTok: https://www.tiktok.com/@johndoe
    [?] Facebook: https://www.facebook.com/johndoe
    [?] X (Twitter): https://x.com/johndoe
    [?] Xbox (3rd-party): https://www.xboxgamertag.com/search/johndoe

(Output above is illustrative. Results depend on the username.)

## Breach checks (optional)
To include Have I Been Pwned breach results for emails, set your own API key first:

    # Mac/Linux
    export HIBP_API_KEY=your-key

    # Windows (Command Prompt)
    set HIBP_API_KEY=your-key

Without a key, the breach check is skipped and everything else still works. Never commit your key to the repo.

## Adding sites
- `sites.json`: sites checked automatically. `{}` is replaced by the username. Add `"error_text"` for sites that return 200 even when the user doesn't exist.
- `manual_sites.json`: sites that block bots. These are printed as links for you to open yourself.

## Limitations
- Results can include false positives or misses if a site changes how it responds.
- Phone numbers can only be validated and described, not matched to accounts.
- Email-derived username matches may belong to a different person.

## License
MIT. See `LICENSE`.
