import ast
import contextlib
import io
import os
import shutil
import tarfile
import tempfile
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

c = TestClient(app)

# Staging root for the fixture below. It lives inside the repository tree on
# purpose - .gitignore lists `backend/tests/_staging/`, so nothing created here
# can ever be committed.
STAGING_ROOT = Path(__file__).resolve().parent / "_staging"


@contextlib.contextmanager
def _fresh_staging_dir():
    """A staging directory the test can actually write to, always cleaned up.

    Deliberately NOT pytest's tmp_path/tmp_path_factory. On the machines this
    suite has to run on that factory is unusable, for two independent reasons:

    * it puts everything under %TEMP%, which the DSH file sandbox denies; and
    * `TempPathFactory` creates every one of its directories with mode 0o700
      (`_pytest/pathlib.py`: `make_numbered_dir(..., mode=0o700)`), and on this
      Windows sandbox a 0o700 `mkdir` yields a directory that cannot be listed
      again at all - `os.scandir()` fails with WinError 5 - so the factory dies
      while it is still searching for a free numbered name.

    Both are fatal to a fixture that only *tries* the factory first, because a
    function containing `yield` is a generator wherever the `yield` sits. The
    previous revision wrote `try: return tmp_path_factory.mktemp(...)` in front
    of the fallback `yield`; on any machine where the factory works that
    `return` ends the generator before it yields, so pytest raised
    `ValueError: staging_dir did not yield a value` and errored every test in
    this file (reproduced: .rd3-probes/fixture/).

    One code path, no %TEMP%, no mode 0o700. Keeping the directory beside the
    tests is also the point of the fallback in the first place: this file once
    mocked the staging dir to Path("."), which dropped an `a.txt` into the
    working tree on every run and got one committed (e4f5fff).
    """
    d = STAGING_ROOT / uuid.uuid4().hex
    d.mkdir(parents=True)
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)
        try:
            STAGING_ROOT.rmdir()  # succeeds only once no other run is using it
        except OSError:
            pass


@pytest.fixture
def staging_dir():
    """Yield one private staging directory per test."""
    with _fresh_staging_dir() as d:
        yield d


def _containers(cont):
    class _Containers:
        def get(self, cid):
            return cont

    class _Client:
        containers = _Containers()

    return _Client()


def test_copy_into_failure_is_reported_and_leaves_no_temp_file(monkeypatch, staging_dir):
    """A failed copy must surface a readable 500 and clean up its staging file."""
    import app.routers.files as files_mod

    class _Missing:
        def put_archive(self, *a, **k):
            raise Exception("no such container")

    monkeypatch.setattr(files_mod, "get_docker_client", lambda: _containers(_Missing()))
    monkeypatch.setattr(files_mod, "get_tmp_dir", lambda: staging_dir)

    r = c.post(
        "/api/containers/missing/copy",
        data={"dest": "/tmp"},
        files={"file": ("a.txt", io.BytesIO(b"hi"), "text/plain")},
    )

    assert r.status_code == 500
    assert "no such container" in r.json()["detail"]
    assert list(staging_dir.iterdir()) == [], "staging file must not survive a failure"


def test_copy_into_success_pushes_a_tar_and_cleans_up(monkeypatch, staging_dir):
    """Happy path: the daemon receives a tar holding exactly the uploaded file."""
    import app.routers.files as files_mod

    captured = {}

    class _Ok:
        def put_archive(self, dest, data):
            captured["dest"] = dest
            captured["data"] = data

    monkeypatch.setattr(files_mod, "get_docker_client", lambda: _containers(_Ok()))
    monkeypatch.setattr(files_mod, "get_tmp_dir", lambda: staging_dir)

    r = c.post(
        "/api/containers/abc/copy",
        data={"dest": "/tmp"},
        files={"file": ("hello.txt", io.BytesIO(b"payload"), "text/plain")},
    )

    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert captured["dest"] == "/tmp"
    with tarfile.open(fileobj=io.BytesIO(captured["data"])) as tar:
        assert tar.getnames() == ["hello.txt"]
        assert tar.extractfile("hello.txt").read() == b"payload"
    assert list(staging_dir.iterdir()) == [], "staging file must be removed on success"


def test_staging_dir_is_writable_and_never_under_tempdir(staging_dir):
    """The fixture must work on a locked-down machine *and* on a normal one.

    RD3-01: the old fixture reported a green suite only on machines whose %TEMP%
    is denied - on a normal machine it errored. Nothing here may depend on
    %TEMP%, so the staging dir must not be inside it, and it must be writable
    even though pytest's own tmp_path machinery is not.
    """
    assert staging_dir.is_dir(), staging_dir

    probe = staging_dir / "probe.txt"
    probe.write_text("ok", encoding="utf-8")
    assert probe.read_text(encoding="utf-8") == "ok"
    probe.unlink()

    temp_root = Path(os.path.normcase(str(Path(tempfile.gettempdir()).resolve())))
    here = Path(os.path.normcase(str(staging_dir.resolve())))
    assert temp_root not in here.parents, (
        f"staging dir {here} must not live under %TEMP% ({temp_root})"
    )


def test_fresh_staging_dir_removes_itself_and_leaves_no_residue():
    """Cleanup contract, driven directly so it is testable without a teardown."""
    with _fresh_staging_dir() as d:
        assert d.is_dir()
        (d / "junk.txt").write_text("x", encoding="utf-8")

    assert not d.exists(), "the per-test staging dir must be removed"
    # The root is removed too as soon as it is empty; if it is still there it
    # must be because another run is using it (never because we left junk).
    if STAGING_ROOT.exists():
        assert list(STAGING_ROOT.iterdir()) != [], (
            f"empty {STAGING_ROOT} must have been removed"
        )


def test_no_fixture_mixes_a_valued_return_with_yield():
    """Structural lock for the RD3-01 defect class.

    A fixture that contains `yield` anywhere is a generator; a bare
    `return <value>` that runs before that yield raises StopIteration on the
    first `next()`, and pytest turns that into
    `ValueError: <name> did not yield a value` - every dependent test ERRORs.
    That failure is invisible on any machine that takes the fallback branch, so
    the only way to catch it everywhere is statically, like this.
    """
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))

    def own_scope(fn):
        """Nodes of fn itself - a nested function's yield does not count."""
        stack = list(ast.iter_child_nodes(fn))
        while stack:
            node = stack.pop()
            if isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)
            ):
                continue
            yield node
            stack.extend(ast.iter_child_nodes(node))

    offenders = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        own = list(own_scope(fn))
        yields = [n.lineno for n in own if isinstance(n, (ast.Yield, ast.YieldFrom))]
        if not yields:
            continue
        first_yield = min(yields)
        for node in own:
            if (
                isinstance(node, ast.Return)
                and node.value is not None
                and node.lineno < first_yield
            ):
                offenders.append(
                    f"{fn.name}(): return with a value at line {node.lineno} "
                    f"precedes its first yield at line {first_yield}"
                )

    assert offenders == [], (
        "these fixtures will raise 'did not yield a value': " + "; ".join(offenders)
    )
