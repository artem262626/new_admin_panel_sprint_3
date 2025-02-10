#!/bin/sh

until curl -s elasticsearch:9200/_cluster/health | grep -qE '"status":"(green|yellow)"'; do
  echo "Waiting for Elasticsearch..."
  sleep 5
done

echo "Elasticsearch is ready!"
exec "$@"
