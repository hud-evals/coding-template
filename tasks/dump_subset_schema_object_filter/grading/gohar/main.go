// Command gohar drives the candidate tree's dump path and nothing else.
//
// It is a separate Go module that compiles against /workspace/repo through a
// replace directive, so it sees only the exported API -- the repo's own test
// helpers are never the oracle. All judgement lives in the Python checks; this
// program's whole job is to turn a job list into dump files plus the errors
// the tree produced along the way.
//
// It also carries the API-shape assertions for criterion 2: the declarations
// below stop compiling the moment the exported shape of the dump API moves,
// which is what the ticket says must not happen.
package main

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"

	pb "github.com/rqlite/rqlite/v10/command/proto"
	rdb "github.com/rqlite/rqlite/v10/db"
	rhttp "github.com/rqlite/rqlite/v10/http"
)

// ─── criterion 2: the exported shape of the dump API stays as it is ────────

var (
	_ func(*rdb.DB, io.Writer, ...string) error = (*rdb.DB).Dump
	_ func(string, bool, bool) (*rdb.DB, error) = rdb.Open
	_ func(rhttp.QueryParams) []string          = rhttp.QueryParams.Tables
	_                                           = pb.BackupRequest{Tables: []string(nil)}
	_ func(*pb.BackupRequest) []string          = (*pb.BackupRequest).GetTables
)

type job struct {
	ID      string   `json:"id"`
	Fixture string   `json:"fixture"`
	Subset  []string `json:"subset"`
	// Restore says whether the dump should also be pushed back through the
	// repo's own restore path (ticket point 1: same file, same result, either
	// reader). Whole-database dumps are never restored.
	Restore bool `json:"restore"`
}

type spec struct {
	FixturesDir string `json:"fixtures_dir"`
	OutDir      string `json:"out_dir"`
	Jobs        []job  `json:"jobs"`
}

type result struct {
	ID           string `json:"id"`
	Dump         string `json:"dump"`
	DumpError    string `json:"dump_error"`
	RepoRestored string `json:"repo_restored"`
	RepoError    string `json:"repo_error"`
	Panic        string `json:"panic"`
}

func main() {
	if len(os.Args) != 2 {
		fmt.Fprintln(os.Stderr, "usage: gohar <spec.json>")
		os.Exit(2)
	}
	raw, err := os.ReadFile(os.Args[1])
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
	var s spec
	if err := json.Unmarshal(raw, &s); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
	if err := os.MkdirAll(s.OutDir, 0o755); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}

	out := make([]result, 0, len(s.Jobs))
	for _, j := range s.Jobs {
		out = append(out, run(s, j))
	}
	enc := json.NewEncoder(os.Stdout)
	enc.SetIndent("", " ")
	if err := enc.Encode(out); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
}

// run produces one dump. A panic out of the tree under test is a verdict, not
// a crash of the grader: it is recorded and the remaining jobs still run.
func run(s spec, j job) (res result) {
	res.ID = j.ID
	defer func() {
		if r := recover(); r != nil {
			res.Panic = fmt.Sprint(r)
		}
	}()

	src := filepath.Join(s.FixturesDir, j.Fixture+".sqlite")
	work := filepath.Join(s.OutDir, j.ID+".src.sqlite")
	if err := copyFile(src, work); err != nil {
		res.DumpError = err.Error()
		return res
	}

	d, err := rdb.Open(work, false, true)
	if err != nil {
		res.DumpError = err.Error()
		return res
	}
	f, err := os.Create(filepath.Join(s.OutDir, j.ID+".sql"))
	if err != nil {
		d.Close()
		res.DumpError = err.Error()
		return res
	}
	dumpErr := d.Dump(f, j.Subset...)
	f.Close()
	d.Close()
	res.Dump = filepath.Join(s.OutDir, j.ID+".sql")
	if dumpErr != nil {
		res.DumpError = dumpErr.Error()
		return res
	}

	if !j.Restore {
		return res
	}

	// Ticket point 1: the same file has to give the same result whether it is
	// sqlite3 or the repo's own restore path that reads it. The Python side
	// compares the two restored databases.
	text, err := os.ReadFile(res.Dump)
	if err != nil {
		res.RepoError = err.Error()
		return res
	}
	dst := filepath.Join(s.OutDir, j.ID+".repo.sqlite")
	os.Remove(dst)
	rd, err := rdb.Open(dst, false, false)
	if err != nil {
		res.RepoError = err.Error()
		return res
	}
	rr, err := rd.ExecuteStringStmt(string(text))
	if err != nil {
		rd.Close()
		res.RepoError = err.Error()
		return res
	}
	for _, x := range rr {
		if e := x.GetError(); e != "" {
			res.RepoError = e
			break
		}
	}
	rd.Close()
	res.RepoRestored = dst
	return res
}

func copyFile(src, dst string) error {
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer in.Close()
	os.Remove(dst)
	out, err := os.Create(dst)
	if err != nil {
		return err
	}
	defer out.Close()
	_, err = io.Copy(out, in)
	return err
}
