#!/usr/bin/env bash
# install-databricks-skills.sh
#
# Installs Databricks AI Dev Kit skills relevant to the Vinoworld Bundle project.
# Skills are installed into .claude/skills/ in the current directory.
#
# Skills selected:
#   databricks-bundles        -- Bundle YAML structure, targets, variable substitution, CLI lifecycle
#   databricks-jobs           -- Multi-task job definition (converting Vinoworld_ELT_Pipeline.yaml)
#   databricks-unity-catalog  -- UC system tables, audit, 3-part naming, access patterns
#   databricks-execution-compute -- Serverless compute configuration (Free Edition constraint)
#   databricks-python-sdk     -- CLI and SDK patterns for workspace interaction
#
# Usage:
#   bash install-databricks-skills.sh
#
# Source: https://github.com/databricks-solutions/ai-dev-kit/tree/main/databricks-skills

set -euo pipefail

SKILLS=(
  databricks-bundles
  databricks-jobs
  databricks-unity-catalog
  databricks-execution-compute
  databricks-python-sdk
)

echo "Installing Databricks AI Dev Kit skills: ${SKILLS[*]}"
echo ""

curl -sSL \
  https://raw.githubusercontent.com/databricks-solutions/ai-dev-kit/main/databricks-skills/install_skills.sh \
  | bash -s -- "${SKILLS[@]}"

echo ""
echo "Done. Skills installed to .claude/skills/"
echo "To list all available skills: curl -sSL https://raw.githubusercontent.com/databricks-solutions/ai-dev-kit/main/databricks-skills/install_skills.sh | bash -s -- --list"
