# Standard container image for local testing, ECS, App Runner, or any host
# that runs a normal HTTP server. For AWS Lambda specifically, use
# Dockerfile.lambda instead (different base image + entry point).

FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir fastapi uvicorn[standard] mangum

COPY src/ ./src/
COPY data/ ./data/
# Copy a pre-trained model in at build/deploy time. In production this
# should instead be pulled from S3 at container startup (see README) so a
# new model version doesn't require rebuilding the image.
COPY models/ ./models/

EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--app-dir", "src"]
