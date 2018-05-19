#!/bin/sh
set -e
if [ -z $PUID ]; then
    echo PUID must be set.
    exit 1
elif [ -z $PGID ]; then
    echo PGID must be set.
    exit 1
fi
chown $PUID:$PGID /source /target
su-exec $PUID:$PGID harmonize -n $NUM_PROCESSES /source /target
