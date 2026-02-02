# apply-branch-protection

Apply cuioss organization branch protection rulesets to a single repository with interactive configuration.

## Workflow

1. **Select Repository**
   - Use `$ARGUMENTS` as repo name, or if "for this repo" use the current repository name
   - For this repository, the name is `cuioss-organization`

2. **Discover Available Checks**
   - Run `./branch-protection/setup-branch-protection.py --repo {repo-name} --list-checks`
   - Parse the JSON output to get available workflow job names

3. **Ask User for Required Status Checks**
   - Use AskUserQuestion with multiSelect=true
   - Filter discovered checks to include only build and analysis jobs:
     - `build (21)`, `build (25)` - Matrix build jobs
     - `sonar-build` - SonarCloud analysis
   - Exclude auxiliary checks: `deploy-snapshot`, `Dependabot`
   - Always include "None (no required checks)" option
   - Header: "Status checks"
   - Question: "Which status checks should be required to pass before merging?"

4. **Ask User for Required Reviews**
   - Use AskUserQuestion
   - Header: "Reviews"
   - Question: "How many approving reviews should be required?"
   - Options:
     - "0 - No reviews required" - Direct pushes allowed for authorized users
     - "1 - One approval required (Recommended)" - Standard review workflow
     - "2 - Two approvals required" - Stricter review for sensitive repos

5. **Preview Changes**
   - Build command with overrides:
     ```
     ./branch-protection/setup-branch-protection.py --repo {repo-name} --diff \
       --required-checks "{comma-separated-checks}" \
       --required-reviews {0|1|2}
     ```
   - If no checks selected, use `--required-checks ""`
   - Parse the JSON output to identify the action needed

6. **Display Configuration Summary**
   - Show the ruleset that will be created/updated:
     ```
     Repository: cuioss/{repo-name}

     Branch Protection Ruleset: main-branch-protection
     - Target: main branch
     - Bypass: cuioss-release-bot
     - Prevent deletion: Yes
     - Block force pushes: Yes
     - Required reviews: {N}
     - Required status checks: {list or "None"}
     ```

7. **Confirm Application**
   - Use AskUserQuestion: "Apply this branch protection ruleset?"
   - Options: "Yes, apply" / "No, cancel"

8. **Apply Changes**
   - If confirmed, run with the same overrides:
     ```
     ./branch-protection/setup-branch-protection.py --repo {repo-name} --apply \
       --required-checks "{comma-separated-checks}" \
       --required-reviews {0|1|2}
     ```
   - Report success or any warnings from the script

## Arguments

- `$ARGUMENTS` - Repository name or "for this repo"

## Example Usage

```
/apply-branch-protection                    # Select repo interactively
/apply-branch-protection cui-java-tools     # Configure and apply to cui-java-tools
/apply-branch-protection for this repo      # Configure and apply to current repo
```

## Script Location

The setup script is located at: `branch-protection/setup-branch-protection.py`

Config file: `branch-protection/config.json`

## CLI Arguments

```
--repo NAME           Target repository
--list-checks         List available workflow checks (JSON output)
--diff                Preview changes (JSON output)
--apply               Apply the ruleset
--required-checks     Comma-separated list of required checks (empty string for none)
--required-reviews    Number of required reviews: 0, 1, or 2
```

## Base Ruleset (always applied)

From `config.json`:
- **Name**: main-branch-protection
- **Target**: main branch
- **Bypass Actor**: cuioss-release-bot (GitHub App)
- **Rules** (always):
  - Prevent deletion
  - Block force pushes
- **Rules** (configurable):
  - Required reviews (0, 1, or 2)
  - Required status checks (user-selected or none)
- **Status check options** (from config):
  - `strict_required_status_checks_policy`: Require branches to be up to date before merging
  - `do_not_enforce_on_create`: Skip enforcement when branch is first created
