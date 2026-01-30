# apply-repo-settings

Apply cuioss organization repository settings to a single repository with preview.

## Workflow

1. **Select Repository**
   - Invoke the `repo-selection` skill with `$ARGUMENTS`
   - This ensures the local clone exists and is up-to-date
   - Retrieve the `repo-name` from the skill output

2. **Preview Changes**
   - Run `./repo-settings/setup-repo-settings.py --repo {repo-name} --diff`
   - Parse the JSON output to identify changes

3. **Display Diff**
   - If no changes needed, inform user: "Repository settings already match desired configuration"
   - If changes exist, display them in a readable format:
     ```
     Repository: cuioss/{repo-name}

     Changes to apply:
     - features.has_wiki: true -> false
     - merge.delete_branch_on_merge: false -> true
     - security.private_vulnerability_reporting: false -> true
     ```

4. **Confirm Application**
   - Use AskUserQuestion: "Apply these repository settings?"
   - Options: "Yes, apply changes" / "No, cancel"

5. **Apply Changes**
   - If confirmed, run `./repo-settings/setup-repo-settings.py --repo {repo-name} --apply`
   - Report success or any warnings from the script

## Arguments

- `$ARGUMENTS` - Optional repository name (passed to repo-selection skill)

## Example Usage

```
/apply-repo-settings                    # Select repo interactively, preview and apply
/apply-repo-settings cui-java-tools     # Preview and apply settings to cui-java-tools
```

## Script Location

The setup script is located at: `repo-settings/setup-repo-settings.py`

Config file: `repo-settings/config.json`

## Settings Applied

From `config.json`:
- **Features**: issues, wiki, projects, discussions toggles
- **Merge**: squash/merge/rebase options, delete branch on merge, commit message format
- **Security**: vulnerability reporting, Dependabot, secret scanning
