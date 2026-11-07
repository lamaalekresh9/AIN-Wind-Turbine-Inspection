# Demo cases: YOLO + VLM

Every way the detector (YOLO) and the vision-language model (VLM) can combine appears in the sample data. The VLM
verdicts are real answers saved in `demo_data/vlm_results.json`, so they show without an API key and survive
`reset-db`. The cases below are in inspections nobody has decided on yet, so the VLM's type corrections and added
defects are applied and the reviewer can decide them live. Sign in as `reviewer@ain.local` / `Review@123`.

| Case | Inspection | Photo | What happens |
|---|---|---|---|
| YOLO detects, VLM agrees | INS-2026-0008 Blade A leading edge (review queue) | DJI_20268643.jpg, DJI_20268866.jpg | YOLO finds corrosion, the VLM confirms it |
| YOLO detects, VLM disagrees | INS-2026-0008 Blade A leading edge (review queue) | DJI_20268806.jpg | YOLO finds corrosion; the VLM says the box is mostly vegetation beyond the blade ("VLM disagrees") |
| YOLO detects, VLM relabels | INS-2026-0008 Blade A leading edge (review queue) | DJI_20268708.jpg | YOLO says corrosion, the VLM relabels it to dirt and the type changes |
| YOLO finds nothing, VLM finds a defect | INS-2026-0004 Blade B close-up (rejected, back with the inspector) | DJI_20268829.jpg, DJI_20268712.jpg | No YOLO box; the VLM adds lightning damage (8829) and dirt (8712) as "Found by VLM" |
| Neither finds a defect | INS-2026-0004 Blade B close-up (rejected, back with the inspector) | DJI_20268626.jpg | No YOLO box and nothing added by the VLM |

INS-2026-0008 shows three cases on one inspection. More examples: INS-2026-0009 (agree, disagree, relabel
surface damage → corrosion), INS-2026-0010 (agree, relabels to dirt), INS-2026-0011 draft (agree and disagree).
The six reviewed inspections (INS-2026-0001 to 0003 and 0005 to 0007) show the VLM opinion beside each finding
without changing the reviewer's decisions.

Inspection codes are numbered by date when the sample data loads, so they are the same on every fresh database.
