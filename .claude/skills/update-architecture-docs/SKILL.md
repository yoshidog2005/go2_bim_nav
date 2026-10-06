---
name: update-architecture-docs
description: Use after a big change in go2_bim_nav, or when the docs were found to be wrong, to update docs/architecture (overall_flow.html, detailed_flow.html, api.html) so they match the code again. A big change adds, removes, renames or rewires a file, class, function, argument, return value, ROS topic/action/tf, launch argument, config value shown in the docs, or a connection between functions or use cases.
---

# Update the architecture docs

`docs/architecture/` holds three views of the same system. After a big change they must still agree with the code and with each other, because the `docs-first-navigation` skill relies on them.

## Is this a big change?

Update the docs if the change does any of these:

- adds, removes or renames a file, class, function or method;
- changes a signature, default, return value, exit code or raised error;
- adds, removes or renames a ROS topic, action, tf frame, node name, launch argument or console command;
- changes a value the pages quote (e.g. speeds, footprint, heights, thresholds in `nav2_params.yaml` or the launch file);
- changes which function's data reaches which other function, or moves work between use cases;
- fixes or creates something marked ⚠ in the docs.

A change that only alters logic inside a function, with the same inputs and outputs, needs no structural update. Still refresh the `file.py:line` references in `api.html` for any file whose line numbers moved.

## Steps

1. **List what changed.** From the diff, write down every changed file, class, function, argument, topic and connection.

2. **api.html (most detailed, update first).** For each changed item, update its entry: signature, parameter table, returns/raises/exits, ROS interface table, "Data in / Data to" links, notes and source line. Add entries for new items in the right use case → file → class; delete entries for removed ones. Element ids follow `module.Class.method` (e.g. `send_goal.GoalSender.send`). The sidebar builds itself from the page.

3. **detailed_flow.html.** Update the matching boxes and function rows (ids like `cb_on`, `itm_raster`) inside the right use-case section. Then update the `GROUPS` edge list in the script: every `f:` and `t:` must be an id that exists on the page, and `what` / `det` / `k` must describe the data actually passed. Use the existing kinds: `topic`, `call`, `file`, `state`, `gap`, `loop`.

4. **overall_flow.html.** Change it only if the big picture moved: a use case, a stage, a top-level arrow, or a design note. Keep its text short.

5. **Keep the conventions.**
   - Colours: blue = workstation, green = this repo's code on the dog, purple = Nav2, orange = Go2 robot, grey dashed = file; red dashed = ⚠ missing or unverified.
   - Remove a ⚠ only once the gap is actually fixed; add one for anything new that is unverified.
   - Pages stay self-contained local HTML (inline CSS/JS, light and dark mode), per the `local-html` skill.

6. **Check it.**
   - Every id referenced in `GROUPS` and every `href="#…"` in `api.html` exists.
   - Render each changed page with headless Edge/Chrome and look at the screenshot, e.g.:
     `msedge --headless=new --disable-gpu --hide-scrollbars --window-size=2100,2600 --screenshot=<scratchpad>/check.png file:///<path>/docs/architecture/detailed_flow.html`
   - Fix overlapping boxes or arrows that pass through cards before finishing.

7. **Report.** Tell the user which pages changed and what changed in each, and any doc claims that were wrong before.
