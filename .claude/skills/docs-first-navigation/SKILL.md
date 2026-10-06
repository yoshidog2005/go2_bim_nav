---
name: docs-first-navigation
description: Use before making any change in go2_bim_nav (fixing a bug, adding a feature, refactoring, debugging, or answering how something works). Build understanding from docs/architecture first, in order overall_flow.html → detailed_flow.html → api.html, then do only a localized code search that widens when the docs look wrong or unclear. Do not start with a repo-wide code search.
---

# Docs-first navigation

This repo has a three-level map of itself in `docs/architecture/`. Use it to understand the space before touching code, instead of searching the whole codebase.

## Steps

1. **Overall flow** — `docs/architecture/overall_flow.html`
   Read the "What each part is for" chart and the stage cards. Decide which use cases the change touches (Mapping, Sensing, Obstacle sensing, Localization, Choosing a goal, Navigation, Driving the robot). The file is small; reading it whole is fine.

2. **Detailed flow** — `docs/architecture/detailed_flow.html`
   Don't read the whole file. Grep for the use case section (`id="uc_map"`, `uc_sense`, `uc_obs`, `uc_loc`, `uc_goal`, `uc_nav`, `uc_drive`) and for the relevant group in the `GROUPS` array in the script. Note:
   - the files, classes and functions in that use case;
   - every edge into and out of them (`f:` / `t:` ids, `what`, `det`, `k`). These are the things the change could break, including edges that cross into other use cases.

3. **API reference** — `docs/architecture/api.html`
   Grep for the functions you found, by element id (e.g. `id="cmd_vel_bridge.CmdVelBridge._on_cmd_vel"`, `id="ifc_to_map.rasterise"`). Take from each entry: signature, parameters, return/exit behaviour, ROS interfaces, data in/out, notes, and the source location (`file.py:line`).

4. **Localized code search**
   Open only the files and line ranges the API entries point to. Widen the search one step at a time (the same function's callers and callees → the rest of that file → other files in the same use case → the rest of the repo) only when:
   - the code disagrees with the docs;
   - a link or piece of data in the docs is unclear;
   - the thing you need isn't in the docs;
   - the change reaches a use case or file the docs don't connect it to.

5. **Report wrong docs**
   If the docs were wrong, tell the user which claim was wrong. Once the change is made, follow the `update-architecture-docs` skill to bring the pages back in line.

## Don'ts

- Don't open with a repo-wide Grep/Glob or by reading every file.
- Don't trust the docs over the code: when they disagree, the code wins, and the docs get fixed.
- If `docs/architecture/` is missing, say so and fall back to a normal search.
