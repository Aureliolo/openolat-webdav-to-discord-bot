# Use an official Python runtime as a base image
FROM python:3.9-slim

# Set the working directory in the container
WORKDIR /usr/src/app

# Copy the requirements.txt file into the container at /usr/src/app
COPY requirements.txt ./

# Install the required Python packages
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your application's code into the container at /usr/src/app
COPY . .

# Set environment variables in .env file or on CLI. or uncomment here and write directly into it.
#ENV WEBDAV_URL=your_webdav_url
#ENV COURSEFOLDERS_PATH=your_root_folder_to_watch
#ENV WEBDAV_LOGIN=your_username
#ENV WEBDAV_PASSWORD=your_password
#ENV DISCORD_WEBHOOK=your_discord_bot_webhook

# Run the bot when the container launches
CMD ["python", "./bot.py"]
