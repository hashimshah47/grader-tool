FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
# Build the sample students used by the demo
RUN python examples/make_samples.py
# Render sets PORT (default 10000); run.py reads it. Bind to all interfaces.
ENV HOST=0.0.0.0
EXPOSE 10000
CMD ["python", "run.py"]
