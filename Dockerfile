# OpenGeoStreams dashboard as a web service (Render, Hugging Face Spaces, any Docker host).
# It starts empty; visitors import their own datasets. River matching uses the India-WRIS
# network bundled in the package (all of India), so no data needs downloading.
FROM python:3.12-slim

WORKDIR /app
# OGS_MAX_DATASETS keeps the newest 4 imports; MALLOC_ARENA_MAX limits memory lost to
# per-thread allocator arenas. Both keep a shared server within a 512 MB free plan.
ENV PYTHONUNBUFFERED=1 \
    OGS_HOST=0.0.0.0 \
    PORT=7860 \
    OGS_MAX_DATASETS=4 \
    MALLOC_ARENA_MAX=2

# Install from a temporary copy: a source folder left in /app would shadow the installed package.
COPY opengeostreams/ /tmp/src/
RUN pip install --no-cache-dir /tmp/src "geopandas>=1.1" "pyarrow>=14" && rm -rf /tmp/src

EXPOSE 7860
CMD ["python", "-m", "opengeostreams.server"]
