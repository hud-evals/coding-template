from collections import defaultdict
from pathlib import Path
from typing import Literal, get_args
from dataclasses import dataclass
from collections import deque
import shlex
import subprocess

from .base import CLIResult, ToolError, ToolResult
from .run import demote, maybe_truncate, run

TRUNCATED_MESSAGE: str = "<response clipped><NOTE>To save on context only part of this file has been shown to you. You should retry this tool after you have searched inside the file with `grep -n` in order to find the line numbers of what you are looking for.</NOTE>"

Command = Literal[
    "view",
    "create",
    "str_replace",
    "insert",
    "undo_edit",
]
SNIPPET_LINES: int = 4

MAX_RESPONSE_LEN: int = 16000

class EditTool:
    """
    An filesystem editor tool that allows the agent to view, create, and edit files.
    The tool parameters are defined by Anthropic and are not editable.
    """

    _file_history: dict[Path, list[str]]

    def __init__(self, run_command_preexec_fn=demote):
        """
        Initialize the EditTool.
        
        Args:
            run_command_preexec_fn: Function to run in child process before executing 
                                   shell commands via the run() utility.
                                   Defaults to demote() which drops privileges to uid/gid 1000.
                                   Pass None to skip preexec, or any callable for custom behavior.
        """
        self._file_history = defaultdict(list)
        self._run_command_preexec_fn = run_command_preexec_fn

    async def __call__(
        self,
        *,
        command: Command,
        path: str,
        file_text: str | None = None,
        view_range: list[int] | None = None,
        old_str: str | None = None,
        new_str: str | None = None,
        insert_line: int | None = None,
    ):
        _path = Path(path)
        self.validate_path(command, _path)
        if command == "view":
            return await self.view(_path, view_range)
        elif command == "create":
            if file_text is None:
                raise ToolError("Parameter `file_text` is required for command: create")
            await self.write_file(_path, file_text)
            self._file_history[_path].append(file_text)
            return ToolResult(output=f"File created successfully at: {_path}")
        elif command == "str_replace":
            if old_str is None:
                raise ToolError("Parameter `old_str` is required for command: str_replace")
            return await self.str_replace(_path, old_str, new_str)
        elif command == "insert":
            if insert_line is None:
                raise ToolError("Parameter `insert_line` is required for command: insert")
            if new_str is None:
                raise ToolError("Parameter `new_str` is required for command: insert")
            return await self.insert(_path, insert_line, new_str)
        elif command == "undo_edit":
            return await self.undo_edit(_path)
        raise ToolError(
            f"Unrecognized command {command}. The allowed commands for the {self.name} tool are: {', '.join(get_args(Command))}"
        )

    def validate_path(self, command: str, path: Path):
        """
        Check that the path/command combination is valid.
        """
        # Check if its an absolute path
        if not path.is_absolute():
            suggested_path = Path("") / path
            raise ToolError(
                f"The path {path} is not an absolute path, it should start with `/`. Maybe you meant {suggested_path}?"
            )
        # Check if path exists
        if not path.exists() and command != "create":
            raise ToolError(f"The path {path} does not exist. Please provide a valid path.")
        if path.exists() and command == "create":
            raise ToolError(f"File already exists at: {path}. Cannot overwrite files using command `create`.")
        # Check if the path points to a directory
        if path.is_dir():
            if command != "view":
                raise ToolError(
                    f"The path {path} is a directory and only the `view` command can be used on directories"
                )

    async def view(self, path: Path, view_range: list[int] | None = None):
        """Implement the view command"""
        if path.is_dir():
            if view_range:
                raise ToolError("The `view_range` parameter is not allowed when `path` points to a directory.")

            _, stdout, stderr = await run(rf"find {path} -maxdepth 2 -not -path '*/\.*'", preexec_fn=self._run_command_preexec_fn)
            if not stderr:
                stdout = f"Here's the files and directories up to 2 levels deep in {path}, excluding hidden items:\n{stdout}\n"
            return CLIResult(output=stdout, error=stderr)

        file_content = await self.read_file(path, truncate_after=None)
        file_text_lines = file_content.splitlines(keepends=True)
        n_lines_file = len(file_text_lines) + (
            1 if file_content.endswith(("\n", "\r\n", "\r")) else 0
        )

        if view_range:
            if len(view_range) != 2 or not all(isinstance(i, int) for i in view_range):
                raise ToolError("Invalid `view_range`. It should be a list of two integers.")
            init_line, final_line = view_range
            if init_line < 1 or init_line > n_lines_file:
                raise ToolError(
                    f"Invalid `view_range`: {view_range}. Its first element `{init_line}` should be within the range of lines of the file: {[1, n_lines_file]}"
                )
            if final_line > n_lines_file:
                raise ToolError(
                    f"Invalid `view_range`: {view_range}. Its second element `{final_line}` should be smaller than the number of lines in the file: `{n_lines_file}`"
                )
            if final_line != -1 and final_line < init_line:
                raise ToolError(
                    f"Invalid `view_range`: {view_range}. Its second element `{final_line}` should be larger or equal than its first `{init_line}`"
                )
            
            # Extract only the requested lines
            if final_line != -1:
                selected_lines = file_text_lines[max(view_range[0] - 1, 0) : view_range[1]]
            else:
                selected_lines = file_text_lines[max(view_range[0] - 1, 0) :]
            # Join without modifying the original line endings
            file_content = "".join(selected_lines)

        file_content = process_view_output_str(
            file_text=file_content,
            path=str(path),
            total_path_lines=n_lines_file,
            max_resp_ln=MAX_RESPONSE_LEN, 
            view_range=(view_range[0], view_range[1]) if view_range else None,
        )

        return CLIResult(output=file_content)

    async def str_replace(self, path: Path, old_str: str, new_str: str | None):
        """Implement the str_replace command, which replaces old_str with new_str in the file content"""
        # Read the file content
        file_content = (await self.read_file(path, truncate_after=1_000_000_000)).expandtabs()
        old_str = old_str.expandtabs()
        new_str = new_str.expandtabs() if new_str is not None else ""

        # Check if old_str is unique in the file
        occurrences = file_content.count(old_str)
        if occurrences == 0:
            raise ToolError(f"No replacement was performed, old_str `{old_str}` did not appear verbatim in {path}.")
        elif occurrences > 1:
            file_content_lines = file_content.split("\n")
            lines = [idx + 1 for idx, line in enumerate(file_content_lines) if old_str in line]
            raise ToolError(
                f"No replacement was performed. Multiple occurrences of old_str `{old_str}` in lines {lines}. Please ensure it is unique"
            )

        # Replace old_str with new_str
        new_file_content = file_content.replace(old_str, new_str)

        # Write the new content to the file
        await self.write_file(path, new_file_content)

        # Save the content to history
        self._file_history[path].append(file_content)

        # Create a snippet of the edited section
        replacement_line = file_content.split(old_str)[0].count("\n")
        start_line = max(0, replacement_line - SNIPPET_LINES)
        end_line = replacement_line + SNIPPET_LINES + new_str.count("\n")
        snippet = "\n".join(new_file_content.split("\n")[start_line : end_line + 1])

        # Prepare the success message
        success_msg = f"The file {path} has been edited. "
        success_msg += self._make_output(snippet, f"a snippet of {path}", start_line + 1)
        success_msg += "Review the changes and make sure they are as expected. Edit the file again if necessary."

        return CLIResult(output=success_msg)

    async def insert(self, path: Path, insert_line: int, new_str: str):
        """Implement the insert command, which inserts new_str at the specified line in the file content."""
        file_text = (await self.read_file(path, truncate_after=1_000_000_000)).expandtabs()
        new_str = new_str.expandtabs()
        file_text_lines = file_text.split("\n")
        n_lines_file = len(file_text_lines)

        if insert_line < 0 or insert_line > n_lines_file:
            raise ToolError(
                f"Invalid `insert_line` parameter: {insert_line}. It should be within the range of lines of the file: {[0, n_lines_file]}"
            )

        new_str_lines = new_str.split("\n")
        new_file_text_lines = file_text_lines[:insert_line] + new_str_lines + file_text_lines[insert_line:]
        snippet_lines = (
            file_text_lines[max(0, insert_line - SNIPPET_LINES) : insert_line]
            + new_str_lines
            + file_text_lines[insert_line : insert_line + SNIPPET_LINES]
        )

        new_file_text = "\n".join(new_file_text_lines)
        snippet = "\n".join(snippet_lines)

        await self.write_file(path, new_file_text)
        self._file_history[path].append(file_text)

        success_msg = f"The file {path} has been edited. "
        success_msg += self._make_output(
            snippet,
            "a snippet of the edited file",
            max(1, insert_line - SNIPPET_LINES + 1),
        )
        success_msg += "Review the changes and make sure they are as expected (correct indentation, no duplicate lines, etc). Edit the file again if necessary."
        return CLIResult(output=success_msg)

    async def undo_edit(self, path: Path):
        """Implement the undo_edit command."""
        if not self._file_history[path]:
            raise ToolError(f"No edit history found for {path}.")

        old_text = self._file_history[path].pop()
        await self.write_file(path, old_text)

        return CLIResult(output=f"Last edit to {path} undone successfully. {self._make_output(old_text, str(path))}")

    async def read_file(self, path: Path, truncate_after: int | None = MAX_RESPONSE_LEN):
        """Read the content of a file from a given path; raise a ToolError if an error occurs."""
        try:
            code, out, err = await run(f"cat {shlex.quote(str(path))}", truncate_after=truncate_after, preexec_fn=self._run_command_preexec_fn)
            if code != 0:
                raise ToolError(f"Ran into {err} while trying to read {path}")
            return out
        except Exception as e:
            print(e)
            raise ToolError(f"Ran into {e} while trying to read {path}") from None

    async def write_file(self, path: Path, file: str):
        """Write the content of a file to a given path; raise a ToolError if an error occurs."""
        try:
            result = subprocess.run(f"sudo -u \\#1000 cat > {path} << 'EOF'\n{file}\nEOF", check=True, shell=True)
        except Exception as e:
            raise ToolError(f"Ran into {e} while trying to write to {path}") from None

    def _make_output(
        self,
        file_content: str,
        file_descriptor: str,
        init_line: int = 1,
        expand_tabs: bool = True,
    ):
        """Generate output for the CLI based on the content of a file."""
        file_content = maybe_truncate(file_content)
        if expand_tabs:
            file_content = file_content.expandtabs()
        file_content = "\n".join([f"{i + init_line:6}\t{line}" for i, line in enumerate(file_content.split("\n"))])
        return f"Here's the result of running `cat -n` on {file_descriptor}:\n" + file_content + "\n"


### AUX utilities

def add_line_numbers(
    text: str, includes_final_line: bool, n_first_line: int = 1
) -> str:
    """
    Given a string, returns the string with line numbers prepended to each line.

    This function:
    - Preserves the original line endings (CR, LF, or CRLF) of each line
    - Adds a tab-separated line number prefix to each line
    - If the text ends with any newline character (\n, \r\n, or \r), adds an
      additional empty numbered line to represent the terminal empty line
    """
    lines_with_endings = text.splitlines(keepends=True)
    result = [
        f"{ind + n_first_line:6}\t{line_with_ending}"
        for ind, line_with_ending in enumerate(lines_with_endings)
    ]

    # Add an extra empty line with line number if original text ends with newline
    if includes_final_line and text.endswith(("\n", "\r\n", "\r")):
        result.append(f"{len(lines_with_endings) + n_first_line:6}\t")

    return "".join(result)


def process_view_output_str(
    file_text: str,
    path: str,
    total_path_lines: int,
    max_resp_ln: int,
    view_range: tuple[int, int] | None = None,
) -> str:
    # Get header
    header = f"Here's the content of {path} with line numbers"
    if total_path_lines is not None and view_range is not None:
        header += f" (which has a total of {total_path_lines} lines) with view_range={list(view_range)}"

    # See if final line is included in the view_range
    if view_range is None or view_range[1] == -1 or view_range[1] == total_path_lines:
        includes_final_line = True
    else:
        includes_final_line = False
    n_first_line = view_range[0] if view_range is not None else 1

    # Truncate if needed
    maybe_truncated_str = truncate_from_middle_v2(
        ss=file_text, max_len=max_resp_ln, n_line_offset=n_first_line - 1
    )
    if isinstance(maybe_truncated_str, str):
        # No truncation
        file_text_with_line_numbers = add_line_numbers(
            file_text,
            includes_final_line=includes_final_line,
            n_first_line=n_first_line,
        )
    else:
        # Truncation occurred
        before_with_line_numbers = add_line_numbers(
            text="".join(maybe_truncated_str.as_str(maybe_truncated_str.before_lines)),
            includes_final_line=False,
            n_first_line=n_first_line,
        )
        if maybe_truncated_str.single_line:
            file_text_with_line_numbers = before_with_line_numbers
        else:
            after_with_line_numbers = add_line_numbers(
                text="".join(
                    maybe_truncated_str.as_str(maybe_truncated_str.after_lines)
                ),
                includes_final_line=includes_final_line,
                n_first_line=1 + maybe_truncated_str.truncated_end_line,
            )
            file_text_with_line_numbers = (
                before_with_line_numbers
                + f"\t{maybe_truncated_str.truncation_msg}"
                + after_with_line_numbers
            )
        
        # Add context-aware truncation message
        if view_range is not None:
            # User already using view_range, suggest adjusting it
            truncation_note = "\n<response clipped><NOTE>To save on context only part of the view range has been shown. You can adjust the view_range parameters or use `grep -n` to find specific content.</NOTE>"
        else:
            # User viewing whole file, suggest view_range or grep
            truncation_note = "\n<response clipped><NOTE>To save on context only part of this file has been shown to you. You can use view_range=[start_line, end_line] to see specific sections, or use `grep -n` to find what you're looking for.</NOTE>"
        
        file_text_with_line_numbers += truncation_note

    return f"{header}:\n{file_text_with_line_numbers}"

@dataclass
class TruncatedString:
    # Blocks
    before_lines: list[str]
    middle_lines: list[str]
    after_lines: list[str]

    # Line numbers (starting from 1)
    truncated_start_line: int
    truncated_end_line: int

    # Truncation msg
    truncation_msg: str
    single_line: bool

    def as_str(self, lines: list[str]) -> str:
        return "".join(lines)

    @property
    def full_truncated_str(self) -> str:
        return "".join(self.before_lines + [self.truncation_msg] + self.after_lines)


def truncate_from_middle_v2(
    ss: str, max_len: int, n_line_offset: int = 0
) -> "str | TruncatedString":
    """
    If no truncation is needed, returns the original string.
    If truncation is needed, returns TruncatedString
    """
    # No truncation needed
    if len(ss) <= max_len:
        return ss

    # Single line
    lines_with_endings = ss.splitlines(True)
    if len(lines_with_endings) == 1:
        chars_per_side = max(1, max_len // 2)
        truncated_char_count = len(ss) - (chars_per_side * 2)
        truncation_msg = f"...< truncated {truncated_char_count} characters >..."

        before_lines = [ss[:chars_per_side] + truncation_msg + ss[-chars_per_side:]]

        return TruncatedString(
            before_lines=before_lines,
            middle_lines=[],
            after_lines=[],
            truncated_start_line=1 + n_line_offset,
            truncated_end_line=1 + n_line_offset,
            truncation_msg=truncation_msg,
            single_line=True,
        )

    # Line truncation
    current_len = 0
    before_lines = []
    middle_lines = deque(lines_with_endings)
    after_lines = deque([])
    while current_len < max_len and len(middle_lines) > 1:
        # Before
        before_candidate_line = middle_lines[0]
        if len(before_candidate_line) + current_len <= max_len:
            before_lines.append(middle_lines.popleft())
            current_len += len(before_candidate_line)
        else:
            break

        # After
        if len(middle_lines) > 1:
            after_candidate_line = middle_lines[-1]
            if len(after_candidate_line) + current_len <= max_len:
                after_lines.appendleft(middle_lines.pop())
                current_len += len(after_candidate_line)
        else:
            break

    # Find truncated lines
    first_truncated_line = 1 + len(before_lines) + n_line_offset
    last_truncated_line = first_truncated_line + len(middle_lines) - 1
    if ss.endswith(("\n", "\r", "\r\n")) and len(after_lines) == 0:
        last_truncated_line += 1

    # Create truncation msg
    if first_truncated_line == last_truncated_line:
        truncation_msg = f"< truncated line {first_truncated_line} >"
    else:
        truncation_msg = (
            f"< truncated lines {first_truncated_line}-{last_truncated_line} >"
        )
    if len(after_lines) != 0:
        if before_lines[0].endswith("\r\n"):
            truncation_msg += "\r\n"
        elif before_lines[0].endswith("\r"):
            truncation_msg += "\r"
        else:
            truncation_msg += "\n"

    return TruncatedString(
        # Blocks
        before_lines=before_lines,
        middle_lines=list(middle_lines),
        after_lines=list(after_lines),
        # Line numbers (starting from 1)
        truncated_start_line=first_truncated_line,
        truncated_end_line=last_truncated_line,
        # Truncation msg
        truncation_msg=truncation_msg,
        single_line=False,
    )