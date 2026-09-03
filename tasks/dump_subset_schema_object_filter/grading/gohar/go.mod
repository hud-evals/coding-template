module gohar

go 1.26.0

require github.com/rqlite/rqlite/v10 v10.0.0

replace github.com/rqlite/rqlite/v10 => __REPO_DIR__

replace github.com/mattn/go-sqlite3 => github.com/rqlite/go-sqlite3 v1.50.0
