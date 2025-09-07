# Pipecat Twilio Voice Agent

A voice AI bot that answers phone calls using Twilio and Pipecat.

## Development Setup

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

## Twilio Setup

### Install Twilio CLI

1. **Install Node.js** (if not already installed):
   ```bash
   curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash -
   sudo apt-get install nodejs -y
   ```

2. **Install Twilio CLI**:
   ```bash
   npm install -g twilio-cli
   ```

3. **Verify installation**:
   ```bash
   twilio --version
   ```

### Configure TwiML Bin

1. **Get your organization name**:
   ```bash
   pcc organizations list
   ```

2. **Create a TwiML Bin** in your Twilio Console with this configuration:
   ```xml
   <?xml version="1.0" encoding="UTF-8"?>
   <Response>
     <Connect>
       <Stream url="wss://api.pipecat.daily.co/ws/twilio">
         <Parameter name="_pipecatCloudServiceHost"
            value="YOUR_AGENT_NAME.YOUR_ORGANIZATION_NAME"/>
       </Stream>
     </Connect>
   </Response>
   ```

3. **Replace placeholders**:
   - `YOUR_AGENT_NAME` with your deployed bot's name (e.g., `pipecat-twilio-voice-agent`)
   - `YOUR_ORGANIZATION_NAME` with your organization name from step 1

4. **Assign TwiML Bin** to your Twilio phone number:
   - Go to Phone Numbers section in Twilio Console
   - Select your phone number
   - Set "A call comes in" to "TwiML Bin"
   - Select your created TwiML Bin
   - Save changes

### Making Test Calls

1. **Set up environment variables**:
   ```bash
   # Create .env file with your credentials
   TWILIO_ACCOUNT_SID=your_account_sid
   TWILIO_AUTH_TOKEN=your_auth_token
   TWIML_BIN_URL=your_twiml_bin_url
   ```

2. **Make an outbound call**:
   ```bash
   set -a && source .env && set +a && twilio api:core:calls:create \
     --from="YOUR_TWILIO_NUMBER" \
     --to="DESTINATION_NUMBER" \
     --url="$TWIML_BIN_URL"
   ```

3. **Replace placeholders**:
   - `YOUR_TWILIO_NUMBER` with your Twilio phone number
   - `DESTINATION_NUMBER` with the number you want to call

## Pipecat Cloud Deployment

Deploy your bot to production using Pipecat Cloud for scaling, monitoring, and global deployment.

### Prerequisites

1. **Sign up for Pipecat Cloud** - Create your account at [Pipecat Cloud](https://cloud.pipecat.ai)
2. **Install Docker** and create a Docker Hub account
3. **Login to Docker Hub**:
   ```bash
   docker login
   ```

### Configure Deployment

1. **Update pcc-deploy.toml** with your Docker Hub username:
   ```toml
   agent_name = "pipecat-twilio-voice-agent"
   image = "YOUR_DOCKERHUB_USERNAME/pipecat-twilio-voice-agent:0.1"
   secret_set = "pipecat-twilio-voice-agent-secrets"
   
   [scaling]
       min_agents = 1
   ```

2. **Set up secrets**:
   ```bash
   # Upload API keys to Pipecat Cloud
   pcc secrets set pipecat-twilio-voice-agent-secrets --file .env
   
   # Set up Docker Hub image pull credentials
   pcc secrets image-pull-secret docker-hub-image-pull-secret https://index.docker.io/v1/
   ```

3. **Build and deploy**:
   ```bash
   # Build and push Docker image
   pcc docker build-push
   
   # Deploy to Pipecat Cloud
   pcc deploy --credentials docker-hub-image-pull-secret
   ```

4. **Connect to your agent**:
   - Open your Pipecat Cloud dashboard
   - Select your agent → **Sandbox**
   - Allow microphone access and click **Connect**

🎉 **Your bot is now live in production!**

## Troubleshooting

- **404 errors**: ngrok tunnel expired, restart `python setup.py --launch-bot`
- **No audio**: Check API keys in `.env`
- **WebSocket errors**: Verify `PIPECAT_PROXY_HOST` matches ngrok URL
- **Docker build issues**: Ensure all system dependencies are installed in Dockerfile