You are working in the repository at /workspace/repo (Go, cgo required, fully offline, no network).
The tree builds already, so an incremental build is enough.

**Subset SQL backups come back broken**

`GET /db/backup?fmt=sql&tables=users,orders` — and `.dump FILE users,orders` in the shell, which
goes through it — is meant to hand you a SQL file that restores those tables into an empty
database. On any database that has indexes, views or triggers in it, the file we hand back does
not do that. Sometimes loading it fails outright; sometimes it loads and leaves you holding a
database whose contents do not work.

What a subset backup has to be: **restoring it gives you what restoring a whole-database backup
would have given you, minus the tables you did not ask for.** Everything else about that database
is unchanged — the same rows, the same answers to the same questions, the same errors where the
original had errors, and the same thing next: what the restored database does on the following
write is what the original would have done. Whatever cannot come out that way does not come at
all; whatever can, must.

Scope — please keep to it:

- A backup with no `tables=` must come out **byte for byte** as it does today, warts and all. This
  ticket is about the subset case.
- Whatever schema `sqlite3` accepts, a backup of it has to work. The databases people hand us are
  not the ones we wrote our tests against.
- `tables=` stays a supported request. Refusing it, or refusing databases that have views or
  triggers in them, is not a fix. It takes whatever the caller sends — a repeated name, an empty
  one, a name that is not a table, one of SQLite's own, a name with punctuation in it — and a
  request the endpoint accepts today it still accepts. What it must never hand back is a file that
  will not restore.
- What comes along comes along as it is: a backup carries the schema, it does not rewrite it.
- The file is plain SQL text and stays that way — the same file has to produce the same database
  whether `sqlite3` reads it or our own restore path does.
- The exported shape of the dump API stays as it is — `Dump(w io.Writer, tableNames ...string)` and
  the HTTP surface. Existing callers must keep compiling.
- Virtual tables (FTS5 and the like) and their shadow tables are out of scope: whole-database
  backups do not round-trip those today either, and that is a separate ticket. ATTACHed databases
  and temp objects are out of scope as well.

Add tests in the repo's style for the behaviour you change. The repo's own gates apply:
`gofmt -l .` clean, `go vet ./...`, and `go test` green on the packages you touch.
