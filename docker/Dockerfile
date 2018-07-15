FROM alpine:edge

RUN apk update && \
    apk add flac lame python3 su-exec && \
    pip3 install harmonize

VOLUME /source
VOLUME /target

ENV NUM_PROCESSES 1
ENV PUID 1000
ENV PGID 1000

ENTRYPOINT chown $PUID:$PGID /source /target && \
           su-exec $PUID:$PGID harmonize -n $NUM_PROCESSES /source /target
