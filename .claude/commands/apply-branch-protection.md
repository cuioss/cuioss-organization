# apply-branch-protection

Apply cuioss organization branch protection rulesets to a single repository with preview.

## Workflow

1. **Select Repository**
   - Invoke the `repo-selection` skill with `$ARGUMENTS`
   - This ensures the local clone exists and is up-to-date
   - Retrieve the `repo-name` from the skill output

2. **Preview Changes**
   - Run `./branch-protection/setup-branch-protection.py --repo {repo-name} --diff`
   - Parse the JSON output to identify the action needed

3. **Display Diff**
   - Based on the `action` field in the diff:
     - `none`: "Branch protection ruleset already matches desired configuration"
     - `create`: "Will create new ruleset '{ruleset_name}'" with details
     - `update`: Show current vs desired comparison

4. **Confirm Application**
   - Use AskUserQuestion: "Apply this branch protection ruleset?"
   - Options: "Yes, apply changes" / "No, cancel"

5. **Apply Changes**
   - If confirmed, run `./branch-protection/setup-branch-protection.py --repo {repo-name} --apply`
   - Report success or any warnings from the script

## Arguments

- `$ARGUMENTS` - Optional repository name (passed to repo-selection skill)

## Example Usage

```
/apply-branch-protection                    # Select repo interactively, preview and apply
/apply-branch-protection cui-java-tools     # Preview and apply ruleset to cui-java-tools
```

## Script Location

The setup script is located at: `branch-protection/setup-branch-protection.py`

Config file: `branch-protection/config.json`

## Ruleset Applied

From `config.json`:
- **Name**: main-branch-protection
- **Target**: main branch
- **Bypass Actor**: cuioss-release-bot (GitHub App)
- **Rules**:
  - Prevent deletion
  - Block force pushes
  - Require pull request with 1 approval
  - Require status checks (build)
