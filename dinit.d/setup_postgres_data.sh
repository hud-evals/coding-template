#!/bin/bash
set -euxo pipefail

if [ ! -f /var/lib/postgresql/16/main/PG_VERSION ]; then
    install -d -o postgres -g postgres -m 700 /var/lib/postgresql/16/main
    sudo -u postgres /usr/lib/postgresql/16/bin/initdb -D /var/lib/postgresql/16/main
fi

