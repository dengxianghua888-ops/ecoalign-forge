"""Run the durable five-case recorded demo without an API key."""

import asyncio
import json

from ecoalign_forge.engine import SynthesisKernel
from ecoalign_forge.policy.builtin import builtin_pack
from ecoalign_forge.schemas.kernel import RunConfig


async def main():
    result = await SynthesisKernel().run(builtin_pack(), RunConfig())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(result["exit_code"])


if __name__ == "__main__":
    asyncio.run(main())
