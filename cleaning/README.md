# Standard data cleanup rules

Applied to a project's tables each time its Zone 1X workspace is built
(`app/cleaning.py`, spec 9.2.1 and 9.2.3). Corrections that are needed again
and again for a variable belong here, as reviewed code; never fix data in
Excel. A one-off wrong value is fixed at the source (REDCap); a correction
for one analysis belongs in that analysis' own script.

    instrument/<table>.py       every row of patients, applications or documents
    instrument/<MODALITY>.py    documents rows of that modality (ECHO, MR, ...)
    cohort/<PREFIX>.py          rows of patients whose code starts with PREFIX

Each file defines:

    def clean(table: str, rows: list[dict]) -> list[dict]:
        """What this rule corrects and why."""
        ...
        return rows

Files starting with `_` are ignored (see `instrument/_example.py`). Each
build writes `cleaning_log.csv` with every rule that ran and how many rows
it changed. Set `CLEANING_DIR` to keep the rules somewhere else.
