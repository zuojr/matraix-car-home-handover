FROM python:3.13-slim
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/journeys
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN git clone https://github.com/holi-lab/SimuHome /opt/SimuHome && cd /opt/SimuHome && git checkout --detach 83d28837b69f0cbf1bc02ed5334cb8b561a9d54d
COPY matraix ./matraix
COPY source-contract.json .
ENV PYTHONPATH=/opt/journeys SIMUHOME_ROOT=/opt/SimuHome PYTHONUNBUFFERED=1
RUN python -c "from matraix.journeys.home.native import load_source; load_source()"
RUN python -c "from matraix.journeys.car.native import load_source; load_source()"
