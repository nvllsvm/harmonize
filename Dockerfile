FROM python:alpine as builder
COPY . .
RUN python setup.py bdist_wheel

FROM python:alpine
COPY --from=builder /dist /dist
RUN apk add flac lame && \
    pip install /dist/*whl && \
    rm -rf ~/.cache /var/cache/apk/*
VOLUME /source /target
ENV NUM_PROCESSES=1
ENTRYPOINT harmonize -n $NUM_PROCESSES /source /target
