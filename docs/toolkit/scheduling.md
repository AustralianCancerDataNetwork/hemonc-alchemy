# Schedules and administration

Use these helpers to read dosing instructions or calculate a treatment timeline from a variant's sigs. Keep the variant attached to its session while related sigs and drugs are loaded.

| Output | Function | Use it for |
| --- | --- | --- |
| Parsed cycle days | `resolve_all_days()` | Reading one `alldays` expression. |
| One instruction per sig | `schedule_events()` | Inspecting source dose, route, phase and cycle fields. |
| Drug/day DataFrame | `administration_frame()` | Comparing administration patterns by drug and route. |
| Sig-level timeline DataFrame | `roll_out_variant()` | Following phases and repeated cycles, with dates where timing can be calculated. |

## Read cycle days

```python
from hemonc_alchemy import resolve_all_days

resolved = resolve_all_days("1,8,15,(+n)")
[day.value for day in resolved.days]  # [1, 8, 15]
resolved.indefinite.kind             # "+n"
```

The continuation marker means the written days are only part of the course. Optional days carry `Day.optional=True`. Unreadable tokens are logged and dropped; an empty day list can indicate an unresolved schedule.

A pipe means a choice of days, with no selected alternative:

```python
resolved = resolve_all_days("7|8|9|10|11|12|13|14|15")
resolved.days                # ()
resolved.choices[0].options   # [7, 8, 9, 10, 11, 12, 13, 14, 15]
```

A numeric continuation such as `(+2)` records an interval of two days in `alldays`, or two cycles in `timing_sequence`. Continuation markers retain the interval without generating future events.

## Inspect dosing instructions

```python
from hemonc_alchemy.toolkit.analytics.treatment.scheduling import schedule_events

for event in schedule_events(variant):
    print(event.sig.id, event.dose_min, event.dose_max, event.dose_unit)
    print(event.cycle_length_lb, event.cycle_length_ub, event.cycle_length_unit)
```

`ScheduleEvent` retains dose and cycle-length bounds in their source form. For example, a bound containing `"1.5-2"` is text and needs an explicit interpretation before numeric analysis. Generated enum fields are enum members. `raw_all_days` contains the original dosing-day expression.

## Build an administration frame

```python
from hemonc_alchemy.toolkit.analytics.treatment.scheduling import (
    administration_frame,
    administration_matrix,
)

frame = administration_frame(variant, decay_days=0)
clinic = frame[frame.route_group == "IV"]
matrix = administration_matrix(frame, route="IV")
```

The frame combines instructions for the same variant, drug, route and day. Repeated cycles have separate rows where `elapsed_day` can be calculated. Pass a list of variants for a combined frame and group results by `variant_cui`.

| Column | Meaning |
| --- | --- |
| `day` | Day within a cycle; lead-in days can be negative. It repeats across cycles. |
| `elapsed_day` | Day relative to variant start; NULL when that position cannot be calculated. |
| `route_group` | `IV` groups clinic-administered routes, including some non-intravenous routes; `PO` groups home-administered routes. |
| `intensity` | Projection weight for the day, including optional-day weighting and any decay tail. |
| `optional` | Whether the dosing day or cycle is optional. |
| `indefinite`, `cycle_indefinite` | Continuation markers for days and cycles respectively. They do not extend the returned rows. |
| `timing_status` | Whether timing was calculated, assumed or unresolved. |

`decay_days=0` returns dosing rows without a decay tail. The default adds two days of decreasing intensity after each dose. These extra rows represent a projection, not extra administrations, and intensity is not a dose amount. Overlapping rows keep the highest intensity.

Rows without a recognized route group or a resolved drug are excluded. A day choice with a resolved drug and route remains as a row with `day` NULL and an unresolved status. The frame can therefore cover only part of a variant's instructions.

`administration_matrix()` pivots the frame by drug and cycle-local `day`, taking the highest intensity across matching rows. It combines repeated cycles and omits days with no entries. Use the timeline below when individual cycles or dates matter.

## Calculate a treatment timeline

```python
from datetime import date
from hemonc_alchemy.toolkit.analytics.treatment.scheduling import roll_out_variant

timeline = roll_out_variant(variant, start_date=date(2026, 1, 1), decay_days=0)
timeline[["sig_id", "phase", "cycle_number", "day", "elapsed_day", "calendar_date", "timing_status"]]
```

### Days and dates

| Column | Meaning |
| --- | --- |
| `day` | Day within the cycle, using the source notation. |
| `phase_elapsed_day` | Zero-based day relative to the phase's first explicit cycle. |
| `elapsed_day` | Zero-based day relative to variant start. |
| `calendar_date` | A timezone-free `datetime.date`, when `start_date` is supplied and timing can be calculated. |

For example, two 21-day cycles with doses on days 1 and 8 produce:

| Cycle | `day` | `elapsed_day` | Date for a 1 January 2026 start |
| --- | --- | --- | --- |
| 1 | 1 | 0 | 1 January |
| 1 | 8 | 7 | 8 January |
| 2 | 1 | 21 | 22 January |
| 2 | 8 | 28 | 29 January |

If an earlier phase has an unknown duration, variant-relative days and dates remain NULL. Phase-relative days can still be available for a later phase whose internal timing is known. An unresolved block also has a NULL phase-relative day.

With `start_date`, month and year cycles use calendar arithmetic. If a phase's start date is unknown, their phase-relative offsets are also NULL. Without `start_date`, calculations use 30-day months and 365-day years.

### Timing rules and status

Phases are ordered by `phase_step`. Cycle blocks within them are placed using their cycle numbers and cycle lengths:

| Source timing | Result |
| --- | --- |
| Adjacent cycle ranges | The following block starts after the preceding block. |
| Overlapping cycle numbers | Blocks share a cycle anchor. Different lengths overlapping across more than one shared cycle leave the later block unresolved. |
| Several preceding blocks end together with different cycle lengths | The following block is unresolved. |
| A phase continues immediately after its predecessor's last cycle number | Cycle numbering continues into that phase. |
| A continuing-cycle marker has no finite end | A later phase cannot be placed from that marker. |

| `timing_status` | Meaning |
| --- | --- |
| `resolved` | Timing could be calculated. |
| `resolved_via_fallback: ...` | Timing uses a stated assumption. Optional cycles are assumed given. |
| `unresolved: ...` | Required timing is missing or ambiguous; the message gives the reason. |

Missing or tied phase steps leave all variant-relative dates NULL. A gap in phase steps leaves dates NULL from the later phase onward. From the first optional cycle, and in later phases, status records the assumption that optional cycles were given.

A choice-only instruction, such as one dose on a day between 7 and 15, remains in the result with `day` NULL and an `unresolved: choice of days ...` status. No alternative is selected automatically.

### Components and source fields

Timeline rows include `sig_id`, `component`, `component_cui`, `phase`, `timing_sequence` and the cycle-length bounds, unit and selection used for the calculation. Use these fields to trace a row back to its instruction. `day_indefinite` and `cycle_indefinite` retain separate day and cycle continuation markers.

`modality` is `systemic`, `radiation`, or NULL for an unclassified sig. Radiation rows can have no resolved drug. Pass `systemic_only=True` to omit radiation rows from the output; their phases still contribute to subsequent timing.
