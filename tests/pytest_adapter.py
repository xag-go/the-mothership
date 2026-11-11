#!/usr/bin/env python3
"""Run pytest-style test functions with the standard library only (no pytest needed).

  python3 tests/pytest_adapter.py path/to/test_file.py

Supports the fixtures the vendored Frugal-Bridge tests use: tmp_path, monkeypatch (setattr, setenv, delenv),
capsys (readouterr). Plain `assert` statements. Prints one line per test and a summary; exit 1 on any failure.
"""
import collections
import importlib.util
import inspect
import io
import os
import pathlib
import shutil
import sys
import tempfile
import traceback

Captured = collections.namedtuple("Captured", "out err")


class MonkeyPatch:
    def __init__(self):
        self._undo = []

    def setattr(self, obj, name, value, raising=True):
        if raising and not hasattr(obj, name):
            raise AttributeError(f"{obj!r} has no attribute {name}")
        old = getattr(obj, name, None)
        had = hasattr(obj, name)
        setattr(obj, name, value)
        self._undo.append(lambda: setattr(obj, name, old) if had else delattr(obj, name))

    def setenv(self, name, value):
        old = os.environ.get(name)
        os.environ[name] = str(value)
        self._undo.append(lambda: os.environ.__setitem__(name, old) if old is not None else os.environ.pop(name, None))

    def delenv(self, name, raising=True):
        if name not in os.environ:
            if raising:
                raise KeyError(name)
            return
        old = os.environ.pop(name)
        self._undo.append(lambda: os.environ.__setitem__(name, old))

    def undo(self):
        for f in reversed(self._undo):
            f()
        self._undo.clear()


class CapSys:
    def __init__(self):
        self.out, self.err = io.StringIO(), io.StringIO()
        self._old = (sys.stdout, sys.stderr)
        sys.stdout, sys.stderr = self.out, self.err

    def readouterr(self):
        r = Captured(self.out.getvalue(), self.err.getvalue())
        self.out.seek(0); self.out.truncate()
        self.err.seek(0); self.err.truncate()
        return r

    def close(self):
        sys.stdout, sys.stderr = self._old


def run_file(path):
    path = pathlib.Path(path).resolve()
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    tests = [(n, f) for n, f in vars(mod).items() if n.startswith("test_") and inspect.isfunction(f)]
    tests.sort(key=lambda t: t[1].__code__.co_firstlineno)
    passed, failed = 0, []
    for name, fn in tests:
        tmp = tempfile.mkdtemp(prefix=f"{name[:20]}-")
        mp, cap = MonkeyPatch(), None
        env = dict(os.environ)
        cwd = os.getcwd()
        kwargs = {}
        try:
            for p in inspect.signature(fn).parameters:
                if p == "tmp_path":
                    kwargs[p] = pathlib.Path(tmp)
                elif p == "monkeypatch":
                    kwargs[p] = mp
                elif p == "capsys":
                    cap = kwargs[p] = CapSys()
                else:
                    raise RuntimeError(f"unsupported fixture: {p}")
            fn(**kwargs)
            ok, err = True, ""
        except Exception:
            ok, err = False, traceback.format_exc()
        finally:
            if cap:
                cap.close()
            mp.undo()
            os.environ.clear(); os.environ.update(env)
            os.chdir(cwd)
            shutil.rmtree(tmp, ignore_errors=True)
        if ok:
            passed += 1
            print(f"PASS {name}")
        else:
            failed.append(name)
            print(f"FAIL {name}\n{err}")
    print(f"{passed} passed, {len(failed)} failed")
    return 1 if failed or not tests else 0


if __name__ == "__main__":
    sys.exit(run_file(sys.argv[1]))
