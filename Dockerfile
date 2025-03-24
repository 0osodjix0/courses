# Use official Python image as a base
FROM python:3.12

# Set the working directory inside the container
WORKDIR /app

# Copy the requirements file into the container
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the bot's code
COPY . .

# Expose the port for webhooks (if needed)
EXPOSE 8000

# Run the bot
CMD ["python", "xcoursestbot.py"]
