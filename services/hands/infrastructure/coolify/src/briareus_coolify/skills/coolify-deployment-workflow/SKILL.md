---
name: coolify-deployment-workflow
description: Operate Briareus Coolify MCP safely with account-scoped read, logs, variables and authorized deployment tools.
---

# Briareus Coolify Hand

This Skill describes the Coolify MCP integration, not general Docker
Compose engineering. The independently installed AI Agent Workflow plugin
provides task-specific deployment and Compose guidance if available; it is
not required for this MCP to operate. No external skill files are downloaded
during Briareus image builds.

1. Identify the selected Coolify account and exact project, server and
   application/service UUID. Inspect live metadata and API permissions.
2. Keep Git desired state, saved Coolify settings and running containers
   distinct. Verify source revision, parser/Compose location, Watch Paths,
   persistent volumes and actual health where the task requires them.
3. Treat application variables and logs as sensitive. Never disclose locked
   or shared values. A two-step sensitive-variable call still needs specific
   operator approval; tool access alone does not authorize disclosure.
4. Deploy/restart only one explicitly authorized resource with confirm=true.
   Treat submission as pending until deployment logs, health and consumer
   acceptance confirm the result. Never touch unrelated resources.
5. Do not infer permission to alter Compose, networking, storage or
   secrets merely from a read-only account or from this Skill.

Available instructions are published locally through skills/list,
skill://coolify-deployment-workflow/SKILL.md and read_project_workflow.
