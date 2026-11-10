# OpenGeoStreams dashboard as a web service (Render, Hugging Face Spaces, any Docker host).
# It starts empty; visitors import their own datasets.
FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    OGS_HOST=0.0.0.0 \
    PORT=7860

# Install from a temporary copy: a source folder left in /app would shadow the installed package.
COPY opengeostreams/ /tmp/src/
RUN pip install --no-cache-dir /tmp/src "geopandas>=1.1" "pyarrow>=14" && rm -rf /tmp/src

EXPOSE 7860
CMD ["python", "-m", "opengeostreams.server"]
