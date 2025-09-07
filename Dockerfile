FROM dailyco/pipecat-starters-twilio:0.1.0

# Install system dependencies for OpenCV and audio processing
# This step is usually not required and not mentioned in the pipecat documentation
RUN apt-get update && apt-get install -y \
    libgl1-mesa-dri \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libgomp1 \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY ./requirements.txt requirements.txt

RUN pip install --no-cache-dir --upgrade -r requirements.txt

COPY ./bot.py bot.py