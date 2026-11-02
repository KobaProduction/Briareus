import type { ConnectionConfiguration, ConnectionProvider } from "./connection-draft"

export interface Connection {
  id: string
  name: string
  provider: ConnectionProvider
  base_url: string
  auth_type: string
  revision: number
  configuration: ConnectionConfiguration
}
export interface ConnectionPage { items: Connection[]; hasMore: boolean; nextCursor: string | null }
export interface ConnectionForms { providers: ConnectionProvider[] }
export interface ConnectionProbe { status: "connected" | "denied" | "unavailable"; identity: string | null }
export type ConnectionSubmission = ConnectionProbe | { item: Connection }
export type ConnectionSubmit = (action: "verify" | "create", configuration: ConnectionConfiguration,
  credential: string) => Promise<ConnectionSubmission | null>
export type ConnectionCommand =
  | { action: "forms" }
  | { action: "list"; cursor?: string }
  | { action: "check"; connection_uuid: string }
  | { action: "delete"; connection_uuid: string; expected_revision: number }
  | { action: "verify" | "create" | "update"; configuration: ConnectionConfiguration; credential: string;
      connection_uuid: string; expected_revision: number | null; alias: string }
