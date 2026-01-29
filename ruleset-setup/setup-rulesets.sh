#!/usr/bin/env bash
# Setup branch protection rulesets across cuioss repositories
# Requires: gh cli, yq (https://github.com/mikefarah/yq)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${1:-$SCRIPT_DIR/config.yml}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Check dependencies
check_dependencies() {
    if ! command -v gh &> /dev/null; then
        log_error "gh cli not found. Install: https://cli.github.com/"
        exit 1
    fi
    if ! command -v yq &> /dev/null; then
        log_error "yq not found. Install: brew install yq"
        exit 1
    fi
    if ! gh auth status &> /dev/null; then
        log_error "Not authenticated with gh. Run: gh auth login"
        exit 1
    fi
}

# Read config values
read_config() {
    ORG=$(yq '.organization' "$CONFIG_FILE")
    BYPASS_ACTOR_NAME=$(yq '.bypass_actor.name' "$CONFIG_FILE")
    BYPASS_ACTOR_TYPE=$(yq '.bypass_actor.type' "$CONFIG_FILE")
    RULESET_NAME=$(yq '.ruleset.name' "$CONFIG_FILE")
    BRANCH_PATTERN=$(yq '.ruleset.branch_pattern' "$CONFIG_FILE")
    ENFORCEMENT=$(yq '.ruleset.enforcement' "$CONFIG_FILE")

    log_info "Organization: $ORG"
    log_info "Bypass Actor: $BYPASS_ACTOR_NAME ($BYPASS_ACTOR_TYPE)"
    log_info "Ruleset: $RULESET_NAME targeting '$BRANCH_PATTERN'"
}

# Get GitHub App ID by name
get_app_id() {
    local app_name="$1"
    local repo="$2"

    # List installations and find the app
    gh api "repos/$ORG/$repo/installation" --jq '.app_id' 2>/dev/null || echo ""
}

# Build ruleset JSON payload
build_ruleset_payload() {
    local bypass_actor_id="$1"

    cat <<EOF
{
  "name": "$RULESET_NAME",
  "target": "branch",
  "enforcement": "$ENFORCEMENT",
  "conditions": {
    "ref_name": {
      "include": ["refs/heads/$BRANCH_PATTERN"],
      "exclude": []
    }
  },
  "bypass_actors": [
    {
      "actor_id": $bypass_actor_id,
      "actor_type": "Integration",
      "bypass_mode": "always"
    }
  ],
  "rules": [
    {
      "type": "deletion"
    },
    {
      "type": "non_fast_forward"
    },
    {
      "type": "pull_request",
      "parameters": {
        "required_approving_review_count": $(yq '.ruleset.rules.require_pull_request.required_approving_review_count' "$CONFIG_FILE"),
        "dismiss_stale_reviews_on_push": $(yq '.ruleset.rules.require_pull_request.dismiss_stale_reviews_on_push' "$CONFIG_FILE"),
        "require_last_push_approval": $(yq '.ruleset.rules.require_pull_request.require_last_push_approval' "$CONFIG_FILE")
      }
    },
    {
      "type": "required_status_checks",
      "parameters": {
        "strict_required_status_checks_policy": $(yq '.ruleset.rules.require_status_checks.strict_required_status_checks_policy' "$CONFIG_FILE"),
        "required_status_checks": [
          $(yq '.ruleset.rules.require_status_checks.required_checks[]' "$CONFIG_FILE" | sed 's/.*/{\"context": "\0"}/' | paste -sd,)
        ]
      }
    }
  ]
}
EOF
}

# Create or update ruleset for a repository
apply_ruleset() {
    local repo="$1"
    local bypass_actor_id="$2"

    log_info "Processing $ORG/$repo..."

    # Check if ruleset exists
    existing_id=$(gh api "repos/$ORG/$repo/rulesets" --jq ".[] | select(.name == \"$RULESET_NAME\") | .id" 2>/dev/null || echo "")

    local payload
    payload=$(build_ruleset_payload "$bypass_actor_id")

    if [[ -n "$existing_id" ]]; then
        log_info "  Updating existing ruleset (ID: $existing_id)"
        gh api -X PUT "repos/$ORG/$repo/rulesets/$existing_id" --input - <<< "$payload" > /dev/null
    else
        log_info "  Creating new ruleset"
        gh api -X POST "repos/$ORG/$repo/rulesets" --input - <<< "$payload" > /dev/null
    fi

    log_info "  ✓ Done"
}

# Main
main() {
    log_info "Ruleset Setup Script"
    log_info "Config: $CONFIG_FILE"
    echo ""

    check_dependencies
    read_config

    # Get bypass actor ID from first repo
    first_repo=$(yq '.repositories[0]' "$CONFIG_FILE")
    log_info "Looking up App ID for $BYPASS_ACTOR_NAME..."

    # Get app installation ID
    app_id=$(gh api "orgs/$ORG/installations" --jq ".installations[] | select(.app_slug == \"$BYPASS_ACTOR_NAME\" or .app_id != null) | .app_id" 2>/dev/null | head -1)

    if [[ -z "$app_id" ]]; then
        log_warn "Could not find app ID automatically."
        read -p "Enter the App ID for $BYPASS_ACTOR_NAME: " app_id
    fi

    log_info "Using App ID: $app_id"
    echo ""

    # Process each repository
    repos=$(yq '.repositories[]' "$CONFIG_FILE")
    for repo in $repos; do
        apply_ruleset "$repo" "$app_id"
    done

    echo ""
    log_info "All rulesets applied successfully!"
}

main "$@"
