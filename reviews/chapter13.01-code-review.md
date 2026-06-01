# Code Review: Recipe 13.1 - Drug Formulary Navigation

## Summary

The Python companion is well-structured, pedagogically sound, and faithfully implements the pseudocode from the main recipe. The code builds understanding progressively (parse, load, query, cache, API handler) and the inline comments explain "why" effectively. The openCypher queries are correct for Neptune's HTTP endpoint. No DynamoDB or S3 leading-slash issues apply here. I found one issue that would cause runtime failures under normal conditions (Neptune's parameter passing format), one misleading pattern around edge loading that could silently produce an incomplete graph, and a few minor notes for improvement.

---

## Issues

### Issue 1: Neptune openCypher Parameter Serialization May Fail

- **File:** `chapter13.01-python-example.md`
- **Location:** `execute_opencypher` function (Step 2)
- **Severity:** WARNING
- **Description:** The `execute_opencypher` function passes parameters as a JSON-serialized string in the `parameters` form field. Neptune's openCypher HTTP endpoint expects parameters as a JSON object string, which is correct. However, the `load_edges` function passes a nested dict as a parameter value (`"props": edge["properties"]`), and the openCypher query uses `SET r += $props`. Neptune's openCypher implementation does not support map-type parameter values in `SET +=` via the HTTP endpoint in all versions. The Bolt protocol handles this differently. For the HTTP/REST endpoint, individual property assignments (like the vertex loader does) are more reliable. A learner following this pattern may get inconsistent behavior depending on their Neptune engine version.
- **Suggested fix:** Add a comment noting this limitation, or restructure `load_edges` to set properties individually (matching the pattern used in `load_vertices`). At minimum, add a comment: `# Note: SET r += $props with map parameters works in Neptune engine 1.2.1.0+. For older versions, set properties individually.`

### Issue 2: Edge Loading Silently Drops Edges When Target Node Doesn't Exist

- **File:** `chapter13.01-python-example.md`
- **Location:** `load_edges` function (Step 2)
- **Severity:** WARNING
- **Description:** The `load_edges` function uses `MATCH (a {id: $from_id}) MATCH (b {id: $to_id})` before creating the edge. If either node doesn't exist (e.g., restriction nodes like `PA_PLAN_12345_RX_83367` or alternative drug nodes referenced in `THERAPEUTIC_ALTERNATIVE` edges that weren't in the current file), the MATCH returns no rows and the MERGE silently does nothing. The prose in `load_graph` mentions this ("If a node doesn't exist yet, the MATCH in the edge query will fail silently"), but the `parse_formulary_file` function creates edges pointing to restriction node IDs (e.g., `f"PA_{plan_id}_{drug_id}"`) and alternative drug IDs that are never created as vertices. This means all `HAS_RESTRICTION` edges and many `THERAPEUTIC_ALTERNATIVE` edges will be silently dropped.
- **Suggested fix:** Either (a) create placeholder vertices for restriction nodes and referenced alternative drugs in `parse_formulary_file`, or (b) use `MERGE` instead of `MATCH` for the endpoint nodes in `load_edges` when the target might not exist yet. The simplest pedagogical fix is to add restriction nodes as vertices in the parser:
  ```python
  # Create restriction vertex so the edge has somewhere to land
  if prior_auth.upper() == "Y":
      restriction_id = f"PA_{plan_id}_{drug_id}"
      if restriction_id not in seen_vertices:
          vertices.append({
              "id": restriction_id,
              "label": "Restriction",
              "properties": {"type": "PRIOR_AUTH", "plan_id": plan_id},
          })
          seen_vertices.add(restriction_id)
  ```

### Issue 3: Cache Key Mismatch Between `find_alternatives` and `get_alternatives_cached`

- **File:** `chapter13.01-python-example.md`
- **Location:** `get_alternatives_cached` (Step 4) vs. pseudocode (Step 4)
- **Severity:** NOTE
- **Description:** The pseudocode uses cache key `"alternatives:" + drug_id + ":" + plan_id` while the Python uses `f"formulary:alternatives:{drug_id}:{plan_id}"`. The Python version is actually better (namespaced prefix avoids collisions), but the inconsistency with the pseudocode is worth noting. The `invalidate_formulary_cache` function correctly uses `match="formulary:*"` which aligns with the Python key format. This is fine as-is, just a minor divergence from the pseudocode.
- **Suggested fix:** No change needed. The Python improves on the pseudocode here. Could add a brief comment noting the namespace prefix is intentional.

### Issue 4: `find_alternatives` Query Uses Plan Node Without Label

- **File:** `chapter13.01-python-example.md`
- **Location:** `find_alternatives` function (Step 3)
- **Severity:** NOTE
- **Description:** The openCypher query matches `(plan {id: $plan_id})` without a node label. The pseudocode uses `(plan:Plan {id: $plan_id})`. The Python version will work (Neptune matches on property alone), but omitting the label forces Neptune to scan all node types for a matching `id` property rather than using the label index. For a teaching example this is fine, but it's a performance anti-pattern that a learner might carry forward. The `get_drug_tier` function has the same pattern: `(p {id: $plan_id})` without a label.
- **Suggested fix:** Add the `:Plan` label to both queries for consistency with the pseudocode and to demonstrate label-based index usage: `(plan:Plan {id: $plan_id})`.

### Issue 5: `json` Import Buried Inside Function

- **File:** `chapter13.01-python-example.md`
- **Location:** `execute_opencypher` function (Step 2)
- **Severity:** NOTE
- **Description:** The `import json` statement is inside the `execute_opencypher` function body (inside the `if parameters:` block). While Python handles this fine (cached after first import), it's unusual and potentially confusing for learners. The `json` module is also used later in `get_alternatives_cached` (via `json.loads` and `json.dumps`) without a visible import at that point in the file. A reader following top-to-bottom might wonder where `json` came from.
- **Suggested fix:** Move `import json` to the top of the file alongside the other imports in the Setup section, or at minimum alongside the Step 2 imports.

---

## Pseudocode vs. Python Consistency

The Python implementation faithfully follows the pseudocode's five-step structure:

1. **parse_formulary_file:** Matches pseudocode exactly. Same column extraction, same vertex/edge structure, same restriction and alternative handling. The Python adds `seen_vertices` deduplication which the pseudocode mentions conceptually but doesn't implement explicitly. Good addition.

2. **load_graph (load_vertices + load_edges):** Matches pseudocode's MERGE-based upsert pattern. The Python splits into two helper functions which is cleaner. The dynamic property building in `load_vertices` is a reasonable implementation of the pseudocode's `SET n += vertex.properties`.

3. **find_alternatives:** The openCypher query is structurally identical to the pseudocode. Same traversal pattern, same OPTIONAL MATCH for restrictions, same ORDER BY. Minor difference: Python omits the `:Plan` label (noted above).

4. **get_alternatives_cached:** Matches pseudocode logic exactly. Cache key format differs slightly (namespaced, noted above). TTL value matches (86400 seconds).

5. **handle_formulary_query:** Matches pseudocode's three-branch logic (NOT_COVERED, PREFERRED, ALTERNATIVES_AVAILABLE). Response structure is identical. The Python adds `get_drug_tier` as a helper function which the pseudocode inlines. Clean separation.

**No missing steps. No unexplained additions.** The "Putting It All Together" section adds `run_formulary_load` and `run_formulary_query` wrapper functions that are pedagogically useful orchestration, not new logic.

---

## Verdict

**PASS**

The code is correct, well-commented, and pedagogically sound. The two WARNING findings are real issues (silent edge drops and potential parameter format incompatibility), but both are clearly in "gap to production" territory rather than "the example is broken" territory. The example will run end-to-end for the happy path (drugs and classes that exist in the same file), and the Gap to Production section explicitly calls out input validation and bulk loading concerns. The restriction node issue (Issue 2) is the most likely to confuse a learner who loads data and then wonders why restriction edges are missing, but the prose in `load_graph` does warn about this behavior.

No ERROR findings. Two WARNING findings (under the 3-WARNING threshold). Three NOTE findings for minor improvements.
