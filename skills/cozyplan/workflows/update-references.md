# Update References

1. Identify the Plan - From the `USER_PROMPT`, locate the target plan `.html` file to update
2. Identify Related Work - Scan the catalog with `PLAN_TOOL brief --all --specs specs` (one line per plan) to find candidates, then determine the other plan(s)/doc(s) and the link direction: back reference (work this plan builds on or depends on) or forward reference (work that builds on or extends this plan)
3. Link Both Sides - For each related plan, run `PLAN_TOOL ref --this TARGET.html --other OTHER.html --type back|forward`. One command handles everything: it adds the reference to the target, adds the reciprocal on the other plan (so links stay bidirectional), stamps `modified` on both, and records an amendment on each. It dedupes, so re-running is safe. (If the other plan lacks anchors, run `PLAN_TOOL init-ids OTHER.html` first.)
4. Report - List each plan touched and the references added in each direction
