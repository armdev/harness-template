The harness report is RED. Do not continue the feature. Fix only the blocking failures, then stop and report.

REPORT
{{report_md}}

For each blocking sensor, in the order listed:
1. Read its "How to fix" line and the guides it names.
2. Make the smallest change that addresses the finding at its cause (the compose key, the migration, the
   query) — not the symptom and not the sensor.
3. Re-run only that sensor with its "Re-run only this" command until it passes.

Then run `make harness-fast` once and confirm the verdict is GREEN.
If a finding looks wrong, do not work around it: quote it, explain why you think it is wrong, and stop.
Blind sensors are harness problems: list them in your reply and leave them alone.
