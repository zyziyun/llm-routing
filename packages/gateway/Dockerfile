FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml requirements.txt ./
RUN pip install --no-cache-dir fastapi uvicorn "pydantic>=2" httpx

COPY src ./src
ENV PYTHONPATH=/app/src
EXPOSE 8000

# Runs on mock providers out of the box. Set EDGE_BACKEND / CHEAP_BACKEND /
# FRONTIER_BACKEND and provider env at `docker run` time to go live.
CMD ["uvicorn", "router.server:app", "--host", "0.0.0.0", "--port", "8000"]
