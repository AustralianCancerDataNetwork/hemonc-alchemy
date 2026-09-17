# Schedules and administration

Scheduling helpers translate the source `alldays` notation into objects that can be inspected or projected into a day-by-day administration view. They do not invent a complete course when the source only specifies part of one.

## Resolve cycle days

```python
from hemonc_alchemy import resolve_all_days

resolved = resolve_all_days("1,8,15,(+n)")
resolved.days       # (Day(1), Day(8), Day(15))
resolved.indefinite # Indefinite(kind="+n", max_days=None)
```

An indefinite marker is preserved. The explicit days are only the portion represented in the source expression; inspect `resolved.indefinite` before treating the list as a complete schedule. Optional days remain marked as optional rather than being silently discarded. Unreadable tokens are reported and dropped according to the parser's documented behavior, so batch analyses should retain parse failures as a data-quality measure.

## Build an administration frame

```python
from hemonc_alchemy.toolkit.analytics.treatment.scheduling import (
    administration_frame,
    administration_matrix,
)

frame = administration_frame(variant, decay_days=0)
clinic = frame[frame.route_group == "IV"]
matrix = administration_matrix(frame)
```

The frame has one row per drug per explicit cycle day. `decay_days=0` gives dosing days only; the default decay adds an intensity tail to the following days for occupancy-style views. Passing a list of variants produces one combined frame, which should be grouped by `variant_cui`, not the human-readable `variant` label.

`route_group == "IV"` is a historical shorthand for clinic-administered routes and includes more than intravenous administration. `"PO"` represents home-administered routes. Unrecognized or unspecified routes are excluded from administration projections rather than guessed at, so the frame may cover less than the source variant.

## Preserve source-shaped values

`ScheduleEvent` keeps fields such as dose and cycle-length bounds in their source form. A value like `"1.5-2"` needs an application decision before it becomes numeric. Generated enum fields remain enum members. Convert these values at the boundary where your application can state its handling of null, uncertain, or non-numeric source values.

## Roll out a complete variant timeline

`roll_out_variant` composes explicit cycle numbers, block-specific cycle lengths, and phase boundaries into a deterministic treatment timeline:

```python
from datetime import date

from hemonc_alchemy.toolkit.analytics.treatment.scheduling import roll_out_variant

timeline = roll_out_variant(variant)
timeline[["drug", "cycle_number", "day", "elapsed_day", "timing_status"]]
```

`elapsed_day` is an integer relative to variant start, where day 0 is the variant start. Pass `start_date` to also receive `calendar_date` values as timezone-free `datetime.date` objects:

```python
timeline = roll_out_variant(variant, start_date=date(2026, 1, 1))
```

Blocks with adjacent cycle-number ranges are anchored sequentially. Blocks with overlapping cycle numbers share the relevant anchor, while genuinely ambiguous source timing remains visible in `timing_status`. The status is `"resolved"`, `"resolved_via_fallback: ..."`, or `"unresolved: ..."`.

`administration_frame` retains its cycle-local `day` column and adds `elapsed_day` and `timing_status`. Variants without resolvable cycle metadata still produce explicitly resolvable administration rows, with a null `elapsed_day` and an unresolved status rather than an invented calendar position. Indefinite (`(+n)`) timing is never sampled by this module; only its explicitly represented cycles are returned.