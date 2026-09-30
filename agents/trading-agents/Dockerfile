FROM python:3.11-slim

WORKDIR /app
RUN pip install "agent-sdk>=0.1.0" requests pydantic

COPY main.py /app/main.py

CMD ["python", "main.py"]
