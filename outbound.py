import os
import sys
import argparse

from dotenv import load_dotenv
from twilio.rest import Client


def build_twiml_url(proxy: str | None, explicit_url: str | None) -> str:
    if explicit_url:
        return explicit_url

    # Allow reading from env if not provided via CLI
    if not proxy:
        proxy = (
            os.getenv("PIPECAT_PROXY_HOST")
            or os.getenv("PROXY_HOST")
            or os.getenv("NGROK_HOST")
        )

    if not proxy:
        print(
            "ERROR: Missing --proxy or --url. Provide --proxy your_ngrok.ngrok.io or --url https://host/",
            file=sys.stderr,
        )
        sys.exit(2)

    # Ensure we only pass the host (run.py expects hostname, not protocol)
    proxy = proxy.replace("http://", "").replace("https://", "").rstrip("/")
    return f"https://{proxy}/"


def main():
    load_dotenv(override=True)

    parser = argparse.ArgumentParser(description="Start a Twilio outbound call to your Pipecat bot")
    parser.add_argument("--to", required=True, help="Destination E.164 number, e.g. +15551234567")
    parser.add_argument(
        "--from",
        dest="from_",
        required=True,
        help="Your Twilio phone number (must be purchased or verified)",
    )
    parser.add_argument(
        "--proxy",
        help="Public hostname where your Pipecat server is reachable (e.g. your_ngrok.ngrok.io)",
    )
    parser.add_argument(
        "--url",
        help="Override TwiML webhook URL. Defaults to https://{proxy}/ if not provided",
    )

    args = parser.parse_args()

    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    if not account_sid or not auth_token:
        print("ERROR: Set TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN in your environment", file=sys.stderr)
        sys.exit(2)

    twiml_url = build_twiml_url(args.proxy, args.url)

    client = Client(account_sid, auth_token)
    call = client.calls.create(
        to=args.to,
        from_=args.from_,
        url=twiml_url,
        method="POST",  # runner's telephony webhook is POST /
    )

    print(f"Initiated call SID: {call.sid}")


if __name__ == "__main__":
    main()