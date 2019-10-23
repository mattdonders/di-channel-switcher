FROM python:3.6
COPY . /app/di-channel-switcher
RUN pip install --upgrade wheel && \
    pip install --upgrade setuptools && \
    pip install -qr /app/di-channel-switcher/requirements.txt

CMD [ "python" , "/app/di-channel-switcher/gameday_channels.py"]
