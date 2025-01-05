FROM python:3.11
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache \
  pip install -r requirements.txt
RUN mkdir -p /app
COPY goodreads.py /app
ENTRYPOINT ["/app/goodreads.py"]
