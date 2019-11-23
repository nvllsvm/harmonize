FROM python:alpine as base

FROM base as builder
WORKDIR /src
COPY . .
RUN python setup.py check && \
    rm -rf dist && \
    python setup.py bdist_wheel

FROM base
LABEL url="https://github.com/nvllsvm/harmonize"
COPY --from=builder /src/dist /dist
RUN apk add --no-cache flac lame opus-tools && \
    pip install --no-cache-dir /dist/*whl && \
    rm -r /dist
ENTRYPOINT ["harmonize"]
