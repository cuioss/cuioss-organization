# repo-selection

Select a cuioss repository and ensure a local clone exists and is up-to-date.

## Workflow

1. **Repository Selection**
   - If a repository name is provided as argument, use it directly
   - Otherwise, list available cuioss repositories using `gh repo list cuioss --limit 100 --json name --jq '.[].name'`
   - Use AskUserQuestion to prompt the user to select a repository

2. **Detect Git Base Path**
   - Determine the git base directory from the current working directory
   - Look for the parent of the current git repository (e.g., `/Users/oliver/git`)
   - If CWD is `/Users/oliver/git/cuioss-organization`, the base path is `/Users/oliver/git`

3. **Check Local Clone**
   - Check if the repository exists at `{git-base-path}/{repo-name}`
   - If the directory exists, verify it's a git repository

4. **Clone or Update**
   - If missing: `gh repo clone cuioss/{repo-name} {git-base-path}/{repo-name}`
   - If exists: `git -C {local-path} pull --ff-only`

5. **Output TOON**
   Return the result in TOON format:
   ```
   repo-name: {repo-name}
   remote-url: https://github.com/cuioss/{repo-name}.git
   local-path: {git-base-path}/{repo-name}
   ```

## Arguments

- `$ARGUMENTS` - Optional repository name (e.g., `cui-java-tools`)

## Example Usage

```
/repo-selection                    # Lists repos and prompts for selection
/repo-selection cui-java-tools     # Uses cui-java-tools directly
```

## Implementation

When invoked:

1. Parse `$ARGUMENTS` for repository name
2. If no repo name provided:
   - Run `gh repo list cuioss --limit 100 --json name --jq '.[].name'` to get repository list
   - Present options to user via AskUserQuestion
3. Detect git base path from CWD
4. Check if `{base-path}/{repo-name}` exists
5. Clone or pull as needed
6. Output the TOON with repo details

## Error Handling

- If `gh` is not authenticated, prompt user to run `gh auth login`
- If clone fails, report the error and suggest manual clone
- If pull fails (e.g., uncommitted changes), warn user and continue with existing state
