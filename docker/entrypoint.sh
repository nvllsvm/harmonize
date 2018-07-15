#!/bin/sh
set -e
chown $PUID:$PGID /source /target
su-exec $PUID:$PGID harmonize -n $NUM_PROCESSES /source /target
