from __future__ import annotations

import logging
import os

from app.seeds.seed_integrations import seed_integrations
from app.seeds.seed_capabilities import seed_capabilities
from app.seeds.seed_packs import seed_packs

log = logging.getLogger("app.seeds")


async def run_all_seeds() -> None:
    """
    Run all seeders in a safe, idempotent manner.
    Controlled by env flags:

      SEED_INTEGRATIONS=1   -> enable integrations seeding (default: 1)
      SEED_CAPABILITIES=1   -> enable capabilities seeding (default: 1)
      SEED_PACKS=1          -> enable packs seeding (default: 1)
    """
    do_integrations = os.getenv("SEED_INTEGRATIONS", "1") in ("1", "true", "True")
    do_capabilities = os.getenv("SEED_CAPABILITIES", "1") in ("1", "true", "True")
    do_packs = os.getenv("SEED_PACKS", "1") in ("1", "true", "True")

    if do_integrations:
        await seed_integrations()
    else:
        log.info("[capability.seeds.integrations] Skipped via env")

    if do_capabilities:
        await seed_capabilities()
    else:
        log.info("[capability.seeds.capabilities] Skipped via env")

    if do_packs:
        await seed_packs()
    else:
        log.info("[capability.seeds.packs] Skipped via env")
