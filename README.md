# Pipecat Twilio Voice Agent

A voice AI bot that answers phone calls using Twilio and Pipecat.

## Setup

1. **Install dependencies**
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. **Configure API keys**
```bash
cp env.example .env
# Edit .env with your keys:
# GOOGLE_API_KEY=...
# TWILIO_ACCOUNT_SID=...
# TWILIO_AUTH_TOKEN=...
# NGROK_AUTHTOKEN=...
```

3. **Run setup script**
```bash
python setup.py --launch-bot
```

This will:
- Start ngrok tunnel
- Update Twilio webhook
- Launch the bot server

## How It Works

### Ngrok Tunneling
- ngrok creates a public URL that forwards to your local server
- Twilio uses this URL to send call data to your bot
- The tunnel stays active while your bot runs

### Twilio Call Flow
1. **Call comes in** → Twilio sends POST to your ngrok URL
2. **Bot responds** → Returns TwiML with WebSocket URL
3. **Audio stream** → Twilio connects to `wss://your-ngrok-url/ws`
4. **Voice conversation** → Real-time audio flows through Pipecat

### Outbound Calls
```bash
python outbound.py --to +1234567890 --from +16602906311
```

## Troubleshooting

- **404 errors**: ngrok tunnel expired, restart `python setup.py --launch-bot`
- **No audio**: Check API keys in `.env`
- **WebSocket errors**: Verify `PIPECAT_PROXY_HOST` matches ngrok URL