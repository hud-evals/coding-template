#!/bin/bash
set -euxo pipefail

echo "Attempting to set up postgres env for ${POSTGRES_USER} on ${POSTGRES_DB}"
until pg_isready; do
    echo "Waiting for postgres to be ready"
    sleep 1
done
echo "Postgres is ready"
echo "Running scripts in /docker-entrypoint-initdb.d"
# run all scripts in /docker-entrypoint-initdb.d (they are bash scripts)
for script in /docker-entrypoint-initdb.d/*.sh; do
    echo "Running script ${script}"
    source ${script}
done