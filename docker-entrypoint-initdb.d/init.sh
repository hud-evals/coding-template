#!/bin/bash

set -e

psql -f /docker-entrypoint-initdb.d/01-init.sql