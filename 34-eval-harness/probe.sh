#!/usr/bin/env bash
set -e
: "${AGENTSWITCH_BASE_URL:?set AGENTSWITCH_BASE_URL}"
: "${AGENTSWITCH_TOKEN:?set AGENTSWITCH_TOKEN}"
echo "BASE=$AGENTSWITCH_BASE_URL"
echo "--- GET /api/ ---"
curl -sS -i -H "Authorization: Bearer $AGENTSWITCH_TOKEN" "$AGENTSWITCH_BASE_URL/api/" | head -40
echo
echo "--- try common list routes ---"
for p in "" "orders/" "records/" "entities/" "tasks/"; do
  code=$(curl -sS -o /tmp/probe.out -w "%{http_code}" -H "Authorization: Bearer $AGENTSWITCH_TOKEN" "$AGENTSWITCH_BASE_URL/api/$p")
  echo "/api/$p -> $code"
  head -c 300 /tmp/probe.out; echo
done
