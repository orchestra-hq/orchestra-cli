def make_git_subprocess_mock(mapping: dict[tuple[str, ...], tuple[int, str, str]]):
    class Result:
        def __init__(self, returncode: int, stdout: str = "", stderr: str = ""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def _mock_run(args, cwd=None, capture_output=False, text=False, check=False):  # noqa: ARG001
        # args begins with ["git", ...]
        key = tuple(args[1:])
        rc, out, err = mapping.get(key, (1, "", ""))
        return Result(rc, out, err)

    return _mock_run
