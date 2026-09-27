"""Durable run, resume, inspect and export commands."""

import argparse
import asyncio
import json
import sys
from decimal import Decimal
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(prog="ecoalign-forge")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--demo", action="store_true", default=None)
    run.add_argument("--mode", choices=["demo", "live"])
    run.add_argument("--num-samples", type=int)
    run.add_argument("--config", type=Path)
    run.add_argument("--policy", type=Path)
    for command in [
        run,
        commands.add_parser("resume"),
        commands.add_parser("inspect"),
        commands.add_parser("export"),
    ]:
        command.add_argument("--data-dir", type=Path)
        command.add_argument("--datasets-dir", type=Path)
        if command is not run:
            command.add_argument("run_dir", type=Path)
        if command.prog.endswith("resume"):
            command.add_argument(
                "--resolve", action="append", default=[], metavar="ATTEMPT_ID=retry|skip"
            )
            command.add_argument("--max-run-cost", type=Decimal)
            command.add_argument("--extend-seconds", type=float, default=0)
    argv = sys.argv[1:]
    if not argv or argv[0].startswith("--"):
        argv = ["run", *argv]
    args = parser.parse_args(argv)

    from ecoalign_forge.engine.kernel import SynthesisKernel
    from ecoalign_forge.policy.builtin import builtin_pack
    from ecoalign_forge.policy.models import PolicyPack
    from ecoalign_forge.runtime.configuration import resolve_config
    from ecoalign_forge.runtime.journal import Journal

    try:
        if args.command == "run":
            if args.demo and args.mode == "live":
                raise ValueError("--demo conflicts with --mode live")
            config = resolve_config(
                path=args.config,
                explicit={
                    "execution_mode": "demo" if args.demo else args.mode,
                    "num_samples": args.num_samples,
                },
            )
            pack = (
                PolicyPack.model_validate_json(args.policy.read_text())
                if args.policy
                else builtin_pack()
            )
        kernel = SynthesisKernel(data_dir=args.data_dir, datasets_dir=args.datasets_dir)
        if args.command == "run":
            result = asyncio.run(kernel.run(pack, config))
        elif args.command == "resume":
            choices = {}
            for value in args.resolve:
                key, choice = value.split("=", 1)
                if key in choices:
                    raise ValueError("Duplicate unknown attempt choice")
                choices[key] = choice
            result = asyncio.run(
                kernel.resume(
                    args.run_dir,
                    unknown_decisions=choices,
                    max_run_cost=args.max_run_cost,
                    extend_seconds=args.extend_seconds,
                )
            )
        else:
            if not (args.run_dir / "run.sqlite3").is_file():
                raise ValueError("No checkpoint at run directory")
            journal = Journal(args.run_dir)
            try:
                if args.command == "inspect":
                    result = kernel._snapshot(journal, persist=False)
                else:
                    with journal.owner():
                        result = {
                            "output_path": str(journal.export(kernel.datasets_dir)),
                            "exit_code": 0,
                        }
            finally:
                journal.close()
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    except KeyboardInterrupt:
        raise SystemExit(130) from None
    except Exception as exc:
        print(f"Pipeline failed: {type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1) from exc
    if "status" in result:
        print(f"Pipeline {result['status']} ({result['execution_mode']})")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(result.get("exit_code", 0) if args.command != "inspect" else 0)


if __name__ == "__main__":
    main()
