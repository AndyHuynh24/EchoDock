"""Windows Search index queries (ADODB, Search.CollatorDSO). Returns nothing if the
index isn't available, and files.py walks the folders instead.
"""

from pathlib import Path

from dock_agent.win.winapi import com_ready

MAX_RESULTS = 500


def _query(where: str, root: Path) -> list[Path]:
    import pywintypes
    import win32com.client
    com_ready()
    scope = "file:" + str(root).replace("\\", "/").replace("'", "''")
    sql = f"SELECT TOP {MAX_RESULTS} System.ItemPathDisplay FROM SystemIndex WHERE SCOPE='{scope}' AND {where}"
    try:
        connection = win32com.client.Dispatch("ADODB.Connection")
        connection.Open("Provider=Search.CollatorDSO;Extended Properties='Application=Windows';")
        records = win32com.client.Dispatch("ADODB.Recordset")
        records.Open(sql, connection)
        found = []
        while not records.EOF:
            found.append(Path(records.Fields.Item("System.ItemPathDisplay").Value))
            records.MoveNext()
        records.Close()
        connection.Close()
        return found
    except pywintypes.com_error as e:
        print(f"Windows Search didn't answer: {e}")
        return []


def names(words: list[str], root: Path, folders: bool | None = None) -> list[Path]:
    """Files or folders whose name has all the words in order. Words are [a-z0-9] only."""
    if not words:
        return []
    where = f"System.FileName LIKE '%{'%'.join(words)}%'"
    if folders is True:
        where += " AND System.Kind = 'folder'"
    return _query(where, root)


def text(words: str, root: Path) -> list[Path]:
    """Files with all these words in their text or name."""
    terms = [w for w in words.split() if w.isalnum()]
    if not terms:
        return []
    return _query("CONTAINS(*, '" + " AND ".join(f'"{t}"' for t in terms) + "')", root)
