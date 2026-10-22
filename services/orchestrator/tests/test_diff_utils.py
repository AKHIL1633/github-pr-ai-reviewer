from diff_utils import chunk_diff, commentable_lines, number_lines, split_diff_by_file

DIFF = """diff --git a/app/db.py b/app/db.py
index 1111111..2222222 100644
--- a/app/db.py
+++ b/app/db.py
@@ -10,4 +10,5 @@ def get_user(conn, user_id):
     cursor = conn.cursor()
-    cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
+    query = f"SELECT * FROM users WHERE id = {user_id}"
+    cursor.execute(query)
     return cursor.fetchone()
@@ -40,2 +41,3 @@ def close(conn):
     conn.close()
+    print("closed")
diff --git a/README.md b/README.md
new file mode 100644
--- /dev/null
+++ b/README.md
@@ -0,0 +1,2 @@
+# Title
+Body
"""


def test_split_diff_by_file():
    files = split_diff_by_file(DIFF)
    assert [path for path, _ in files] == ["app/db.py", "README.md"]
    assert files[1][1].startswith("diff --git a/README.md")


def test_commentable_lines_tracks_new_file_numbers_across_hunks():
    lines = commentable_lines(DIFF)
    # Hunk 1 starts at 10: context(10), removed(-), added(11), added(12), context(13)
    # Hunk 2 starts at 41: context(41), added(42)
    assert lines["app/db.py"] == {10, 11, 12, 13, 41, 42}
    assert lines["README.md"] == {1, 2}


def test_removed_lines_are_not_commentable():
    lines = commentable_lines(DIFF)
    numbered = number_lines(split_diff_by_file(DIFF)[0][1])
    removed = next(l for l in numbered.splitlines() if 'id = %s"' in l)
    assert removed.startswith("      -")  # no line number on removed lines
    assert len(lines["app/db.py"]) == 6


def test_number_lines_prefixes_added_lines():
    numbered = number_lines(split_diff_by_file(DIFF)[0][1])
    assert '   11 +    query = f"SELECT * FROM users WHERE id = {user_id}"' in numbered
    assert "   42 +    print(\"closed\")" in numbered


def test_chunk_diff_keeps_files_whole_and_respects_budget():
    chunks = chunk_diff(DIFF, max_chars=500)
    assert len(chunks) == 2
    assert "app/db.py" in chunks[0] and "README.md" not in chunks[0]
    assert "README.md" in chunks[1]


def test_chunk_diff_single_chunk_when_small():
    assert len(chunk_diff(DIFF)) == 1


def test_chunk_diff_empty():
    assert chunk_diff("") == []
