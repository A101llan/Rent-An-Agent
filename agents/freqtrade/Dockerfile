FROM freqtradeorg/freqtrade:stable

USER root
RUN pip install "agent-sdk>=0.1.0"
USER ftuser

COPY main.py /freqtrade/user_data/main.py

ENTRYPOINT ["python3", "/freqtrade/user_data/main.py"]
