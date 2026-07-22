from harness.cmd import test as testcmd


def test_build_argv_targets_pytest():
    argv = testcmd._pytest_argv([])
    assert argv[0].endswith("python") or "python" in argv[0]
    assert "pytest" in argv


def test_build_argv_passthrough():
    argv = testcmd._pytest_argv(["tests/test_config.py", "-k", "foo"])
    assert "tests/test_config.py" in argv and "-k" in argv and "foo" in argv
