FROM python:alpine as builder
COPY . .
RUN python setup.py bdist_wheel

FROM python:alpine
COPY --from=builder /dist /dist
RUN apk add flac lame su-exec && \
    pip install /dist/*whl && \
    rm -rf ~/.cache /var/cache/apk/*
VOLUME /source /target
ENV NUM_PROCESSES=1 PUID=1000 PGID=1000
ENTRYPOINT chown $PUID:$PGID /target && \
           su-exec $PUID:$PGID harmonize -n $NUM_PROCESSES /source /target
