# Public snapshot scope

This standalone public repository has a new root commit; it does not publish the original private Git history. The source snapshot is `9e432e33f868170915ecde0b1b16e27b3cb8e3e1`. User authorization covers publication of the required upstream code. Existing private fork and PR #15 are left unchanged.

Core runtime, task, scoring and native integration sources remain byte-identical to that snapshot. Public wrapper changes are the root README/HANDOVER, this note, CI trigger on main, and retaining only scripted CI summaries as uploaded artifacts. This is prospective journey-sidecar-v10 / structured-journeys-v4 code, not a claim that an older study used this corrected protocol.

Excluded: real/source persona datasets (including the upstream validation subset), human text samples, saved curation outputs, research runs, notebooks with embedded outputs, generated PDFs and unrelated upstream CI workflows. Formal Car/Home study data were never part of this snapshot. The seed-42 synthetic developer fixtures needed by existing tests remain, with an explicit fixture notice. No model credentials are provided.

The public CI installs in a clean Linux checkout and runs real Docker/Harbor with scripted API services. Trial/persona trees created for acceptance remain temporary; only summary verifier/ACCEPTANCE.json files are uploaded. New actual model interfaces require a separately authorized compatibility pilot. Windows Docker Desktop/WSL and cloud execution are not claimed verified.

See PUBLIC_HANDOVER_MANIFEST.json for source hashes and exclusions. Keep new persona pools, keys, API receipts, results and reports outside Git. The public repository is a runnable handover, not a historical experiment-results archive.
