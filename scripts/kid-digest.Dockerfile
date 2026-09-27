# Runs scripts/kid-digest.py on the NAS via Synology Container Manager, on an
# hourly Task Scheduler trigger. This image only provides the Python runtime;
# the actual repo checkout, private state directory, and SSH deploy key are
# bind-mounted at run time (see the docker run command in the repo's plan/
# setup notes) so the image itself stays stateless and rebuildable.
#
# Build (from the repo root):
#   docker build -t kid-digest -f scripts/kid-digest.Dockerfile .

FROM python:3.14-slim

RUN apt-get update && apt-get install -y --no-install-recommends git openssh-client \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    cryptography \
    openai \
    pymupdf

WORKDIR /repo

ENTRYPOINT ["python3", "scripts/kid-digest.py"]
