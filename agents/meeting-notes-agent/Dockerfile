FROM python:3.13-slim
WORKDIR /app
RUN pip install fastapi uvicorn
COPY main.py .
EXPOSE 8080
USER nobody
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
