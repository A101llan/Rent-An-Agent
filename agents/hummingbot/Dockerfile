FROM coinalpha/hummingbot:latest

# Hummingbot runs as root in their default container, or hummingbot user
RUN pip install "agent-sdk>=0.1.0"

COPY main.py /home/hummingbot/main.py

ENTRYPOINT ["python3", "/home/hummingbot/main.py"]
