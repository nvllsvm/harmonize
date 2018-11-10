ARG BASE_IMAGE=python:alpine

FROM ${BASE_IMAGE} as builder
WORKDIR /repo
COPY . .
RUN python setup.py bdist_wheel

FROM ${BASE_IMAGE}
COPY --from=builder /repo/dist /dist
RUN apk add --no-cache flac lame && \
    pip install --no-cache-dir /dist/*whl
ENTRYPOINT ["harmonize"]
