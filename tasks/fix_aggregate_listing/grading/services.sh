#!/usr/bin/env bash
# DynamoDB Local on 127.0.0.1:8000 for the connected suites. Returns once it
# answers; whatever it leaves running is killed by the env at grade time.
set -u
cd /opt/dynamodb-local
java -Djava.library.path=/opt/dynamodb-local/DynamoDBLocalLib -jar DynamoDBLocal.jar -inMemory -port 8000 \
  >"${GRADING_LOGS_DIR:-/tmp}/dynamodb.log" 2>&1 &
for _ in $(seq 1 240); do
  (exec 3<>/dev/tcp/127.0.0.1/8000) 2>/dev/null && exit 0
  sleep 0.5
done
echo "DynamoDB Local did not become ready" >&2
exit 1
