#!/bin/bash
# Atlona Broker Client
# 
# Usage:
#   atlona-client.sh <command>
#   atlona-client.sh Status
#   atlona-client.sh "x1AVx9"   # Route input 1 to output 9
#   atlona-client.sh BROKER:STATUS
#   atlona-client.sh BROKER:WAIT  # Wait for connection
#
# Environment variables:
#   ATLONA_BROKER_HOST - Broker host (default: localhost)
#   ATLONA_BROKER_PORT - Broker port (default: 2323)

BROKER_HOST="${ATLONA_BROKER_HOST:-localhost}"
BROKER_PORT="${ATLONA_BROKER_PORT:-2323}"

if [ -z "$1" ]; then
    echo "Usage: $0 <command>"
    echo ""
    echo "Commands:"
    echo "  Status              - Get routing status"
    echo "  x<N>AVx<M>          - Route input N to output M"
    echo "  BROKER:STATUS       - Get broker status"
    echo "  BROKER:WAIT         - Wait for Atlona connection"
    echo "  BROKER:RECONNECT    - Force reconnection"
    exit 1
fi

# Send command and get response
echo "$1" | nc -w 5 "$BROKER_HOST" "$BROKER_PORT"
