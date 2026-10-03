# Test tooling (contract suite, unit tests, eval). Not deployed; runs under the `tools` compose profile.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY libs/common /libs/common
COPY tools/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir "/libs/common[kafka]" -r /tmp/requirements.txt
WORKDIR /repo
