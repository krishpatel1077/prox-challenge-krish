FROM python:3.11-slim

# Create non-root user — this is what fixes the Agent SDK root restriction
RUN useradd -m -u 1000 appuser

WORKDIR /app

# Install dependencies as root first
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all project files
COPY . .

# Switch to non-root user before running
USER appuser

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
