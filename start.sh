#!/usr/bin/env bash
# Easypanel start: worker + dashboard API in one service so they share
# /app/messages and /app/transcripts. Exits if either process dies.
set -e
python -m receptionist.agent start &
WORKER=$!
python api_server.py &
API=$!
wait -n $WORKER $API
