import re

FILE_HEADER = re.compile(r"^diff --git a/(.+?) b/(.+)$", re.MULTILINE)
HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def split_diff_by_file(diff: str) -> list[tuple[str, str]]:
    """Split a unified diff into (path, file_diff) pairs, using the post-change path."""
    matches = list(FILE_HEADER.finditer(diff))
    files = []
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(diff)
        files.append((match.group(2), diff[match.start():end]))
    return files


def _walk_hunks(file_diff: str):
    """Yield (new_line_number | None, raw_line) for every line of a single-file diff.

    The number is the line's position in the new file for added and context lines,
    and None for headers and removed lines.
    """
    new_line = None
    for line in file_diff.splitlines():
        hunk = HUNK_HEADER.match(line)
        if hunk:
            new_line = int(hunk.group(1))
            yield None, line
        elif new_line is None or line.startswith("-") or line.startswith("\\"):
            yield None, line
        else:
            yield new_line, line
            new_line += 1


def number_lines(file_diff: str) -> str:
    """Prefix each added/context line with its new-file line number.

    LLMs are bad at counting lines inside hunks; giving them the number explicitly
    is what makes inline comments land on the right line.
    """
    out = []
    for number, line in _walk_hunks(file_diff):
        out.append(f"{number:>5} {line}" if number is not None else f"      {line}")
    return "\n".join(out)


def commentable_lines(diff: str) -> dict[str, set[int]]:
    """Lines on the RIGHT side of the diff that GitHub accepts review comments on."""
    return {
        path: {number for number, _ in _walk_hunks(file_diff) if number is not None}
        for path, file_diff in split_diff_by_file(diff)
    }


def chunk_diff(diff: str, max_chars: int = 12000) -> list[str]:
    """Group per-file, line-numbered diffs into chunks that fit in one LLM prompt.

    Files are never split across chunks; a single file larger than max_chars is truncated.
    """
    files = split_diff_by_file(diff)
    if not files:
        return [diff[:max_chars]] if diff.strip() else []

    chunks, current = [], ""
    for _, file_diff in files:
        numbered = number_lines(file_diff)[:max_chars]
        if current and len(current) + len(numbered) > max_chars:
            chunks.append(current)
            current = ""
        current += numbered + "\n"
    if current:
        chunks.append(current)
    return chunks
