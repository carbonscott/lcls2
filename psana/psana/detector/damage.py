"""
Take the detector segments and manage xtc._damage fields.

Note that each level of xtc class has _damage property:
  d._xtc
  d.xppcspad[0]._xtc
  d.xppcspad[0].raw._xtc
, but we only make the alg level (raw, fex, etc.) xtc._damage
available through the interface below.
"""

from dataclasses import dataclass
from enum import Enum

DAMAGE_USERBITSHIFT = 12
DAMAGE_VALUEBITMASK = 0x0FFF


class DamageBitmask(Enum):
    """Damage types as an Enum: Truncated=1, OutOfOrder=2, OutOfSynch=3, Corrupted=4,
    DroppedContribution=5, MissingData=6, TimedOut=7, UserDefined=8.

    `Damage` uses `1 << MissingData.value` as the damage value for missing segments.
    """
    Truncated = 1  # bitmask 0
    OutOfOrder = 2
    OutOfSynch = 3
    Corrupted = 4
    DroppedContribution = 5
    MissingData = 6
    TimedOut = 7
    UserDefined = 8  # bitmask 12

    def size(self):
        """Return `len(self.__dict__["_member_names_"])`.

        Called on a member this raises KeyError, because `_member_names_` is in the class `__dict__`,
        not in a member's; `DamageBitmask.size(DamageBitmask)` returns the number of members (8).
        """
        return len(self.__dict__["_member_names_"])


@dataclass
class DamageInfo:
    """Damage information of one event.

    `counts` maps a damage value to a per-segment list of 0/1 flags, `userbits` is a per-segment
    list, `evt` is the event it was computed for, and `sum_recorded` tells whether it was added to
    the running sum.
    """
    counts: dict = None
    userbits: list = None
    evt: object = None
    sum_recorded: bool = False

    def loaded(self, evt):
        """Return True if this info was computed for the same event object `evt` (identity check)."""
        return self.evt is evt


class Damage:
    """Per-event damage summary of one detector data type (`det_alg`, for example `det.raw`).

    Damage is read from the `_xtc.damage` field of the detector's segments. Calling the object is the
    same as `count(evt)`; results are cached for the last event, and `count` adds each new event to
    a running per-segment sum returned by `sum()`.
    """
    def __init__(self, det_alg):
        self.det_alg = det_alg
        self.segments = det_alg._segments
        self._damage_info = DamageInfo()
        self._sum_damage_counts = {}

    def __call__(self, evt):
        return self.count(evt)

    def _expected_segments(self):
        return list(getattr(self.det_alg, "_sorted_segment_inds", []))

    def _damage_vector(self, segment_ids):
        if not segment_ids:
            return []
        return [0] * (max(segment_ids) + 1)

    def _event_damage(self, evt):
        damage = 0
        for dgram in getattr(evt, "_dgrams", []):
            if dgram is None or not hasattr(dgram, "_xtc"):
                continue
            damage |= dgram._xtc.damage & DAMAGE_VALUEBITMASK
        return damage

    def _evt_segments(self, evt):
        det_name = getattr(self.det_alg, "_det_name", None)
        drp_class_name = getattr(self.det_alg, "_drp_class_name", None)
        if det_name is None or drp_class_name is None:
            return {}
        return getattr(evt, "_det_segments", {}).get((det_name, drp_class_name), {})

    def _add_damage(self, damage_counts, damage, segment_id, segment_ids):
        damage &= DAMAGE_VALUEBITMASK
        if not damage:
            return
        if damage not in damage_counts:
            damage_counts[damage] = self._damage_vector(segment_ids)
        damage_counts[damage][segment_id] = 1

    def _add_to_sum(self):
        for damage, segment_counts in self._damage_info.counts.items():
            if damage not in self._sum_damage_counts:
                self._sum_damage_counts[damage] = list(segment_counts)
            else:
                self._sum_damage_counts[damage] = [
                    sum_count + evt_count
                    for sum_count, evt_count in zip(
                        self._sum_damage_counts[damage], segment_counts
                    )
                ]
        self._damage_info.sum_recorded = True

    def _load_damage_info(self, evt, flag_sum=False):
        if self._damage_info.loaded(evt):
            if flag_sum and not self._damage_info.sum_recorded:
                self._add_to_sum()
            return

        "Get segments of det/alg for this event and return damage info"
        segments = self.segments(evt)

        # Idea 1: damage_counts can be global and we only keep the sum
        expected_segments = self._expected_segments()
        segment_ids = expected_segments
        evt_segments = segments if segments is not None else self._evt_segments(evt)
        if evt_segments:
            segment_ids = sorted(set(segment_ids) | set(evt_segments.keys()))
        damage_counts = {}
        userbits = self._damage_vector(segment_ids)

        present_segments = set()
        if evt_segments:
            for segment_id, segment in evt_segments.items():
                present_segments.add(segment_id)
                if hasattr(segment, "_xtc") and segment._xtc.damage:
                    userbits[segment_id] = segment._xtc.damage >> DAMAGE_USERBITSHIFT
                    self._add_damage(
                        damage_counts, segment._xtc.damage, segment_id, segment_ids
                    )

        missing_segments = set(expected_segments) - present_segments
        if missing_segments:
            damage = self._event_damage(evt)
            if not damage and present_segments:
                damage = 1 << DamageBitmask.MissingData.value
            if damage:
                for segment_id in missing_segments:
                    self._add_damage(damage_counts, damage, segment_id, segment_ids)

        self._damage_info = DamageInfo(damage_counts, userbits, evt)
        if flag_sum:
            self._add_to_sum()

    def count(self, evt, flag_sum=True):
        """Return the damage counts of `evt` as {damage value: list of 0/1 flags indexed by segment id}.

        The damage value is a segment's `_xtc.damage` masked to its low 12 bits. Expected segments that
        are missing get the OR of the event dgrams' damage, or MissingData (1 << 6) if that is 0 and
        some segments are present. With `flag_sum` True the counts are added to the running sum once per
        event.
        """
        self._load_damage_info(evt, flag_sum=flag_sum)
        return self._damage_info.counts

    def userbits(self, evt):
        """Return a list, indexed by segment id, of each damaged segment's `_xtc.damage >> 12`.

        Undamaged and missing segments give 0. Does not add the event to the running sum.
        """
        self._load_damage_info(evt)
        return self._damage_info.userbits

    def sum(self):
        """Return the running sum {damage value: per-segment counts} built by `count` calls with `flag_sum=True`."""
        return self._sum_damage_counts
