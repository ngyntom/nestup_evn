import logging
from ..types import EVN_NAME
from .base import EVNRegion
from .hanoi import HanoiRegion
from .hcmc import HCMCRegion
from .npc import NPCRegion
from .cpc import CPCRegion
from .spc import SPCRegion

_LOGGER = logging.getLogger(__name__)

REGION_MAP = {
    EVN_NAME.HANOI: HanoiRegion,
    EVN_NAME.HCMC: HCMCRegion,
    EVN_NAME.NPC: NPCRegion,
    EVN_NAME.CPC: CPCRegion,
    EVN_NAME.SPC: SPCRegion,
}

__all__ = ["HanoiRegion", "HCMCRegion", "NPCRegion", "CPCRegion", "SPCRegion", "REGION_MAP"]
