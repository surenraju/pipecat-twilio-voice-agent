import os
import asyncio
from datetime import datetime

from dotenv import load_dotenv
from loguru import logger

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.processors.frameworks.rtvi import RTVIConfig, RTVIObserver, RTVIProcessor
from pipecat.runner.types import (
    RunnerArguments,
    SmallWebRTCRunnerArguments,
    WebSocketRunnerArguments,
)
from pipecatcloud.agent import DailySessionArguments
from pipecat.runner.utils import parse_telephony_websocket
from pipecat.serializers.twilio import TwilioFrameSerializer
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.services.llm_service import FunctionCallParams
from pipecat.transports.base_transport import BaseTransport, TransportParams
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
from pipecat.services.gemini_multimodal_live.gemini import GeminiMultimodalLiveLLMService

# Load environment variables (API keys, Twilio, etc.)
load_dotenv(override=True)


async def run_bot(transport: BaseTransport):
    logger.info(f"Starting bot")

    # LLM: generate responses and call tools (Cerebras)
    llm = GeminiMultimodalLiveLLMService(
        api_key=os.getenv("GOOGLE_API_KEY"),
        model_id="gemini-live-2.5-flash-preview-native-audio",
        voice_id="Puck",  # Aoede, Charon, Fenrir, Kore, Puck
    )

    # Prompt: set system role and current time context
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    messages = [
        {
            "role": "system",
            "content": f"You are a receptionist for a Dubai based RESTAURANT called The Salusbury. You are on a phone call and therefore the users inputs are coming from a transcription model so take that into account. Respond naturally, concisely and keep your answers conversational as these will be spoken by a text to speech model. Your goal is to take the users request and to try to help them as best you can. Before using check_availability, ensure the user has provided a valid date and time and party size and also let them know that you will check availability and then call the function.\n\nContext: {now}",
        },
    ]

    # Tool: function the LLM can call to check availability
    tools = [
        {
            "type": "function",
            "function": {
                "name": "check_availability",
                "description": "Check table availability. Always returns that a table is available.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "date": {
                            "type": "string",
                            "description": "Desired date (YYYY-MM-DD)",
                        },
                        "time": {
                            "type": "string",
                            "description": "Desired time (HH:MM, 24h)",
                        },
                        "party_size": {
                            "type": "integer",
                            "description": "Number of guests",
                        },
                    },
                    "required": ["date", "time", "party_size"],
                },
            },
        }
    ]

    # LLM context and aggregator (manages messages and tool calls)
    context = OpenAILLMContext(messages, tools=tools, tool_choice="auto")

    # Register function handler for tool calls
    async def check_availability(params: FunctionCallParams):
        await asyncio.sleep(2)
        await params.result_callback({"available": True})

    llm.register_function("check_availability", check_availability)
    context_aggregator = llm.create_context_aggregator(context)

    # RTVI: normalize and route frames/events between steps
    rtvi = RTVIProcessor(config=RTVIConfig(config=[]))

    pipeline = Pipeline(
        [
            transport.input(),
            context_aggregator.user(),
            llm,
            transport.output(),
            context_aggregator.assistant(),
        ]
    )

    # Task: run pipeline with audio settings and metrics enabled
    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            audio_in_sample_rate=8000,
            audio_out_sample_rate=8000,
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
        observers=[RTVIObserver(rtvi)],
    )

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info(f"Client connected")
        # On connect: send a greeting prompt to kick off the conversation
        messages.append({"role": "system", "content": "Say something like 'Thank you for calling, The Salusbury how can I help you today?'"})
        await task.queue_frames([context_aggregator.user().get_context_frame()])

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info(f"Client disconnected")
        # On disconnect: stop the pipeline task
        await task.cancel()

    # Run the pipeline
    runner = PipelineRunner(handle_sigint=False)

    await runner.run(task)


async def bot(runner_args: RunnerArguments):
    """Main bot entry point compatible with WebRTC and Twilio transports."""

    transport = None

    if isinstance(runner_args, SmallWebRTCRunnerArguments):
        logger.info("Using WebRTC transport")
        transport = SmallWebRTCTransport(
            params=TransportParams(
                audio_in_enabled=True,
                audio_out_enabled=True,
                vad_analyzer=SileroVADAnalyzer(),
            ),
            webrtc_connection=runner_args.webrtc_connection,
        )

    elif isinstance(runner_args, WebSocketRunnerArguments):
        logger.info("Using WebSocket transport (Twilio/Telephony)")
        # Parse the websocket URL to auto-detect Twilio transport and call data
        transport_type, call_data = await parse_telephony_websocket(runner_args.websocket)
        logger.info(f"Auto-detected telephony transport: {transport_type}")

        # Twilio serializer: attach call identifiers and credentials
        serializer = TwilioFrameSerializer(
            stream_sid=call_data["stream_id"],
            call_sid=call_data["call_id"],
            account_sid=os.getenv("TWILIO_ACCOUNT_SID", ""),
            auth_token=os.getenv("TWILIO_AUTH_TOKEN", ""),
        )

        # Transport: FastAPI WebSocket with audio in/out, VAD, and serialization
        transport = FastAPIWebsocketTransport(
            websocket=runner_args.websocket,
            params=FastAPIWebsocketParams(
                audio_in_enabled=True,
                audio_out_enabled=True,
                add_wav_header=False,
                vad_analyzer=SileroVADAnalyzer(),
                serializer=serializer,
            ),
        )

    elif isinstance(runner_args, DailySessionArguments):
        logger.info("Using Daily.co session transport")
        # For Daily.co sessions, we can use the same WebRTC transport
        # but with Daily-specific connection handling
        transport = SmallWebRTCTransport(
            params=TransportParams(
                audio_in_enabled=True,
                audio_out_enabled=True,
                vad_analyzer=SileroVADAnalyzer(),
            ),
            webrtc_connection=runner_args.webrtc_connection,
        )

    else:
        logger.error(f"Unsupported runner arguments type: {type(runner_args)}")
        return

    if transport is None:
        logger.error("Failed to create transport")
        return

    # Start the bot using this transport
    await run_bot(transport)


if __name__ == "__main__":
    from pipecat.runner.run import main

    # CLI entrypoint
    main()