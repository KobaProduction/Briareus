import {readBoundedJsonResponse,readBoundedErrorCode} from "@/shared/lib/transport"
import {CONTROL_PANEL_API_V1} from "@/shared/config"
/** LOCAL Backend source contract: _oidc_catalog.py GET /api/v1/catalog.
 * Exact nonsecret Resource owner metadata; credentials/variables values never
 * leave Catalog SQL or enter the browser. This is NOT an MCP effect grant.
 */
import type { VerifiedPlatformContext } from "@/entities/workspace"

import { hasCurrentProject, validUuid, parseCatalogMetadata, type CatalogKind, type CatalogMetadataResult } from "../model/catalog-metadata"
export { CATALOG_PAGE_LIMIT, parseCatalogMetadata } from "../model/catalog-metadata"
export type { CatalogKind, CatalogSummary, CatalogMetadataResult } from "../model/catalog-metadata"

function cancelled(): CatalogMetadataResult { return { kind: "unavailable", code: "CATALOG_READ_CANCELLED" } }
async function catalogFailure(response: Response, signal: AbortSignal): Promise<CatalogMetadataResult> {
  const code = await readBoundedErrorCode(response, signal, "UNKNOWN")
  if (signal.aborted) return cancelled()
  const status: Partial<Record<number, "unauthorized" | "forbidden" | "invalid">> = {
    401: "unauthorized", 403: "forbidden", 422: "invalid",
  }
  return { kind: status[response.status] ?? "unavailable", code }
}
async function catalogSuccess(response: Response, signal: AbortSignal, project: string,
  kind: CatalogKind, context: VerifiedPlatformContext): Promise<CatalogMetadataResult> {
  const value: unknown = await readBoundedJsonResponse(response, signal, 65_536)
  if (signal.aborted) return cancelled()
  const items = parseCatalogMetadata(value, project, kind, context)
  return items ? { kind: "ready", items } : { kind: "invalid", code: "CATALOG_DTO_INVALID" }
}

export async function readCurrentCatalog(
  project:string,
  kind:CatalogKind,
  context:VerifiedPlatformContext,
  signal:AbortSignal,
):Promise<CatalogMetadataResult> {
  if(!validUuid(project)||!(kind==="integration"||kind==="variable")||!hasCurrentProject(context,project))
    return {kind:"forbidden",code:"CATALOG_PROJECT_PERMISSION_DENIED"}
  if(signal.aborted)return cancelled()
  try{
    const response=await fetch(
      `${CONTROL_PANEL_API_V1}/catalog?project_uuid=${encodeURIComponent(project)}&kind=${kind}`,
      {method:"GET",signal,credentials:"same-origin",mode:"same-origin",
        redirect:"error",referrerPolicy:"no-referrer",cache:"no-store",
        headers:{Accept:"application/json"}},
    )
    if(signal.aborted)return cancelled()
    return response.status === 200 ? await catalogSuccess(response, signal, project, kind, context) : await catalogFailure(response, signal)
  }catch{return {kind:"unavailable",code:signal.aborted?"CATALOG_READ_CANCELLED":"CATALOG_NETWORK_UNAVAILABLE"}}
}
