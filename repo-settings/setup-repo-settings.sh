#!/usr/bin/env bash
# Apply consistent repository settings across cuioss repositories
# Requires: gh cli, yq (https://github.com/mikefarah/yq)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${1:-$SCRIPT_DIR/config.yml}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_section() { echo -e "\n${BLUE}=== $1 ===${NC}"; }

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
    log_info "Organization: $ORG"
    log_info "Config file: $CONFIG_FILE"
}

# Apply repository settings
apply_repo_settings() {
    local repo="$1"
    log_section "Configuring $ORG/$repo"

    # Build JSON payload for repo settings
    local has_issues=$(yq '.features.has_issues' "$CONFIG_FILE")
    local has_wiki=$(yq '.features.has_wiki' "$CONFIG_FILE")
    local has_projects=$(yq '.features.has_projects' "$CONFIG_FILE")
    local has_discussions=$(yq '.features.has_discussions' "$CONFIG_FILE")

    local allow_squash=$(yq '.merge.allow_squash_merge' "$CONFIG_FILE")
    local allow_merge=$(yq '.merge.allow_merge_commit' "$CONFIG_FILE")
    local allow_rebase=$(yq '.merge.allow_rebase_merge' "$CONFIG_FILE")
    local delete_branch=$(yq '.merge.delete_branch_on_merge' "$CONFIG_FILE")
    local allow_auto_merge=$(yq '.merge.allow_auto_merge' "$CONFIG_FILE")
    local squash_title=$(yq '.merge.squash_merge_commit_title' "$CONFIG_FILE")
    local squash_message=$(yq '.merge.squash_merge_commit_message' "$CONFIG_FILE")

    log_info "Applying repository settings..."
    gh api -X PATCH "repos/$ORG/$repo" \
        -f has_issues="$has_issues" \
        -f has_wiki="$has_wiki" \
        -f has_projects="$has_projects" \
        -f has_discussions="$has_discussions" \
        -f allow_squash_merge="$allow_squash" \
        -f allow_merge_commit="$allow_merge" \
        -f allow_rebase_merge="$allow_rebase" \
        -f delete_branch_on_merge="$delete_branch" \
        -f allow_auto_merge="$allow_auto_merge" \
        -f squash_merge_commit_title="$squash_title" \
        -f squash_merge_commit_message="$squash_message" \
        > /dev/null 2>&1 && log_info "  ✓ Repository settings applied" || log_warn "  ⚠ Some settings may require admin access"
}

# Apply security settings
apply_security_settings() {
    local repo="$1"

    local vuln_reporting=$(yq '.security.private_vulnerability_reporting' "$CONFIG_FILE")
    local dependabot_alerts=$(yq '.security.dependabot_alerts' "$CONFIG_FILE")
    local dependabot_updates=$(yq '.security.dependabot_security_updates' "$CONFIG_FILE")
    local secret_scanning=$(yq '.security.secret_scanning' "$CONFIG_FILE")
    local push_protection=$(yq '.security.secret_scanning_push_protection' "$CONFIG_FILE")

    log_info "Applying security settings..."

    # Private vulnerability reporting
    if [[ "$vuln_reporting" == "true" ]]; then
        gh api -X PUT "repos/$ORG/$repo/private-vulnerability-reporting" \
            > /dev/null 2>&1 && log_info "  ✓ Private vulnerability reporting enabled" || log_warn "  ⚠ Could not enable vulnerability reporting"
    fi

    # Dependabot alerts
    if [[ "$dependabot_alerts" == "true" ]]; then
        gh api -X PUT "repos/$ORG/$repo/vulnerability-alerts" \
            > /dev/null 2>&1 && log_info "  ✓ Dependabot alerts enabled" || log_warn "  ⚠ Could not enable Dependabot alerts"
    fi

    # Dependabot security updates
    if [[ "$dependabot_updates" == "true" ]]; then
        gh api -X PUT "repos/$ORG/$repo/automated-security-fixes" \
            > /dev/null 2>&1 && log_info "  ✓ Dependabot security updates enabled" || log_warn "  ⚠ Could not enable Dependabot updates"
    fi

    # Secret scanning (requires GitHub Advanced Security for private repos)
    # For public repos, this is available on free tier
    if [[ "$secret_scanning" == "true" ]]; then
        gh api -X PATCH "repos/$ORG/$repo" \
            --field security_and_analysis='{"secret_scanning":{"status":"enabled"}}' \
            > /dev/null 2>&1 && log_info "  ✓ Secret scanning enabled" || log_warn "  ⚠ Secret scanning may require GHAS"
    fi

    # Secret scanning push protection
    if [[ "$push_protection" == "true" ]]; then
        gh api -X PATCH "repos/$ORG/$repo" \
            --field security_and_analysis='{"secret_scanning_push_protection":{"status":"enabled"}}' \
            > /dev/null 2>&1 && log_info "  ✓ Push protection enabled" || log_warn "  ⚠ Push protection may require GHAS"
    fi
}

# Verify settings
verify_settings() {
    local repo="$1"

    log_info "Verifying settings..."

    # Check vulnerability reporting
    local vuln_status=$(gh api "repos/$ORG/$repo/private-vulnerability-reporting" --jq '.enabled' 2>/dev/null || echo "unknown")
    if [[ "$vuln_status" == "true" ]]; then
        log_info "  ✓ Private vulnerability reporting: enabled"
    else
        log_warn "  ⚠ Private vulnerability reporting: $vuln_status"
    fi

    # Check repo settings
    local settings=$(gh api "repos/$ORG/$repo" --jq '{has_issues, has_wiki, delete_branch_on_merge}' 2>/dev/null)
    log_info "  Current settings: $settings"
}

# Main
main() {
    log_info "Repository Settings Setup Script"
    echo ""

    check_dependencies
    read_config

    # Process each repository
    repos=$(yq '.repositories[]' "$CONFIG_FILE")
    for repo in $repos; do
        apply_repo_settings "$repo"
        apply_security_settings "$repo"
        verify_settings "$repo"
        echo ""
    done

    log_info "All repository settings applied!"
}

main "$@"
