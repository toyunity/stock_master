"""개발 하네스 진입점: python -m harness <verify|test|eval|ops>."""
import argparse
import importlib
import sys

_COMMANDS = ("verify", "test", "eval", "ops")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="harness", description="Stock Master 개발 하네스")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in _COMMANDS:
        sub.add_parser(name, add_help=False)  # 각 커맨드가 자체 인자 파싱
    args, rest = p.parse_known_args(argv)
    mod = importlib.import_module("harness.cmd." + args.cmd)
    return int(mod.main(rest) or 0)


if __name__ == "__main__":
    sys.exit(main())
