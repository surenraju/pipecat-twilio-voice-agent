import argparse
import os
import sys
import time
import subprocess
from typing import Optional

from dotenv import load_dotenv
from twilio.base.exceptions import TwilioRestException
from twilio.rest import Client


def _print_numbers(numbers):
    print()
    print("Available Twilio phone numbers:")
    for idx, num in enumerate(numbers, start=1):
        fn = num.friendly_name or ""
        current = f" (current URL: {num.voice_url})" if getattr(num, "voice_url", None) else ""
        print(f"  {idx}. {num.phone_number}  {fn}{current}")
    print()


def _select_number_interactive(client: Client) -> str:
    numbers = client.incoming_phone_numbers.list(limit=50)
    if not numbers:
        print("No incoming phone numbers found in your Twilio account.", file=sys.stderr)
        sys.exit(2)

    _print_numbers(numbers)

    while True:
        choice = input(
            "Enter the number of the phone to configure (or paste +E.164 or a PhoneNumber SID): "
        ).strip()

        if not choice:
            continue

        # By index
        if choice.isdigit():
            idx = int(choice)
            if 1 <= idx <= len(numbers):
                return numbers[idx - 1].sid
            print("Invalid selection. Try again.")
            continue

        # By +E.164
        if choice.startswith("+"):
            matches = [n for n in numbers if n.phone_number == choice]
            if matches:
                return matches[0].sid
            print("No matching phone number found. Try again.")
            continue

        # By SID
        if choice.upper().startswith("PN") and len(choice) == 34:
            return choice

        print("Unrecognized input. Provide a list index, +E.164 phone number, or PN SID.")


def _extract_host_from_url(url: str) -> str:
    # Assumes https://host[/]
    host = url.replace("https://", "").replace("http://", "")
    return host.rstrip("/")


def _start_ngrok_and_get_url(port: int = 7860) -> str:
    """Start an ngrok HTTPS tunnel to the given port and return the public URL.

    Prefers pyngrok if available. Requires NGROK_AUTHTOKEN for stable use.
    """
    try:
        from pyngrok import conf as ngrok_conf  # type: ignore
        from pyngrok import ngrok  # type: ignore

        region = os.getenv("NGROK_REGION")  # e.g., "us"
        authtoken = os.getenv("NGROK_AUTHTOKEN")

        if region:
            ngrok_conf.get_default().region = region
        if authtoken:
            ngrok.set_auth_token(authtoken)

        tunnel = ngrok.connect(port, proto="http", bind_tls=True)
        public_url = tunnel.public_url
        if not public_url.startswith("https://"):
            # pyngrok sometimes returns http first; prefer https
            # Open a second https tunnel specifically
            ngrok.disconnect(public_url)
            tunnel = ngrok.connect(port, proto="http", bind_tls=True)
            public_url = tunnel.public_url

        return public_url
    except Exception as e:
        print("Failed to start ngrok via pyngrok:", e, file=sys.stderr)
        print("Ensure pyngrok is installed and NGROK_AUTHTOKEN is set (recommended).", file=sys.stderr)
        sys.exit(2)


def _update_twilio_webhooks(
    client: Client, phone_sid: str, public_url: str, set_fallback: bool = True
) -> None:
    """Update Twilio IncomingPhoneNumber webhook settings to use POST to public_url.

    Sets both primary voice_url and voice_fallback_url to the same URL by default.
    """
    # Ensure trailing slash
    if not public_url.endswith("/"):
        public_url = public_url + "/"

    try:
        update_kwargs = {
            "voice_url": public_url,
            "voice_method": "POST",
        }
        if set_fallback:
            update_kwargs.update({
                "voice_fallback_url": public_url,
                "voice_fallback_method": "POST",
            })

        number = client.incoming_phone_numbers(phone_sid).update(**update_kwargs)
        print()
        print(f"Updated {number.phone_number} (SID: {number.sid})")
        print(f"  A call comes in → Webhook (HTTP POST): {public_url}")
        if set_fallback:
            print(f"  Primary handler fails → Webhook (HTTP POST): {public_url}")
        print()
    except TwilioRestException as tre:
        print(f"Twilio API error: {tre}", file=sys.stderr)
        sys.exit(2)


def maybe_update_env_proxy(public_url: str, env_path: str = ".env") -> None:
    try:
        host = _extract_host_from_url(public_url)
        print(f"Detected proxy host: {host}")
        ans = input("Write PIPECAT_PROXY_HOST to .env? [Y/n]: ").strip().lower()
        if ans not in ("n", "no"):  # default yes
            # Read existing
            lines: list[str] = []
            if os.path.exists(env_path):
                with open(env_path, "r", encoding="utf-8") as f:
                    lines = f.read().splitlines()

            found = False
            for i, line in enumerate(lines):
                if line.startswith("PIPECAT_PROXY_HOST="):
                    lines[i] = f"PIPECAT_PROXY_HOST={host}"
                    found = True
                    break
            if not found:
                lines.append(f"PIPECAT_PROXY_HOST={host}")

            with open(env_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")

            print(f"Wrote PIPECAT_PROXY_HOST to {env_path}")
    except Exception as e:
        print(f"Warning: failed to update {env_path}: {e}")


def main():
    load_dotenv(override=True)

    parser = argparse.ArgumentParser(
        description=(
            "Start ngrok, grab the public URL, and update Twilio 'A call comes in' webhook to POST."
        )
    )
    parser.add_argument("--port", type=int, default=7860, help="Local server port to expose")
    parser.add_argument("--sid", help="Incoming PhoneNumber SID (PN...) to configure")
    parser.add_argument("--to", dest="phone_number", help="Phone number (+E.164) to configure")
    parser.add_argument(
        "--no-fallback",
        action="store_true",
        help="Do not set the 'Primary handler fails' fallback webhook",
    )
    # Persistent by default; allow opt-out
    parser.add_argument(
        "--stay-running",
        dest="stay_running",
        action="store_true",
        default=True,
        help="Keep the ngrok tunnel running (default)",
    )
    parser.add_argument(
        "--no-stay-running",
        dest="stay_running",
        action="store_false",
        help="Do not keep the tunnel running after updating Twilio",
    )
    parser.add_argument(
        "--launch-bot",
        action="store_true",
        help="Launch the bot server with the detected proxy host",
    )

    args = parser.parse_args()

    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    if not account_sid or not auth_token:
        print("ERROR: Set TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN in your environment", file=sys.stderr)
        sys.exit(2)

    client = Client(account_sid, auth_token)

    # Determine which phone number to configure
    phone_sid: Optional[str] = args.sid
    if not phone_sid and args.phone_number:
        # Resolve by E.164
        nums = client.incoming_phone_numbers.list(limit=100)
        match = next((n for n in nums if n.phone_number == args.phone_number), None)
        if match:
            phone_sid = match.sid
        else:
            print("No phone number found matching", args.phone_number, file=sys.stderr)
            sys.exit(2)

    if not phone_sid:
        phone_sid = _select_number_interactive(client)

    # Start ngrok and obtain public URL
    public_url = _start_ngrok_and_get_url(args.port)
    print(f"ngrok public URL: {public_url}")

    # Update Twilio number config
    _update_twilio_webhooks(
        client, phone_sid, public_url, set_fallback=not args.no_fallback
    )

    # Offer to update .env
    maybe_update_env_proxy(public_url)

    host = _extract_host_from_url(public_url)
    print("Next steps:")
    print(f"  1) Ensure the bot server is running: python bot.py --transport twilio --proxy {host}")
    print("  2) Call your Twilio number to test the inbound call.")
    print(f"  3) Make a call to your own number to test the outbound call: python outbound.py --to +NUMBER_TO_CALL --from +NUMBER_FROM --proxy {host}")
    print()

    # Optionally launch the bot server for convenience
    if args.launch_bot:
        print("Launching bot server...")
        try:
            subprocess.Popen(
                [
                    sys.executable,
                    "bot.py",
                    "--transport",
                    "twilio",
                    "--proxy",
                    host,
                ]
            )
            print("Bot server started in background.")
        except Exception as e:
            print(f"Failed to launch bot server automatically: {e}", file=sys.stderr)

    if args.stay_running:
        print("ngrok tunnel is active. Press Ctrl+C to stop.")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            print("\nStopping...")


if __name__ == "__main__":
    main()