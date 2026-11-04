"""The typed result of Chromium's developerPrivate synchronization."""

from __future__ import annotations

from briareus_json_values import JsonObject, json_object
from pydantic import BaseModel, Field


class ExtensionSyncResult(BaseModel):
    id: str
    userScriptsAccess: bool
    ok: bool
    error: str = ""


class DeveloperSyncResult(BaseModel):
    inDeveloperMode: bool | None = None
    extensions: list[ExtensionSyncResult] = Field(default_factory=list)
    eligibleExtensionIds: list[str] = Field(default_factory=list)

    def failure_details(self) -> str:
        failures = [item for item in self.extensions if not item.ok]
        return "; ".join(f"{item.id}: {item.error or 'unknown error'}" for item in failures[:5])

    def response(self, enabled: bool) -> JsonObject:
        return {
            "in_developer_mode": self.inDeveloperMode,
            "user_scripts_enabled": enabled,
            "user_scripts_extension_count": len(set(self.eligibleExtensionIds)),
            "extensions": [
                json_object(item.model_dump(exclude_defaults=True)) for item in self.extensions
            ],
        }


DEVELOPER_SYNC_SCRIPT = """
                async ({enabled, extensionIds, updateProfileMode}) => {
                  if (!chrome?.developerPrivate) {
                    throw new Error(
                      'chrome.developerPrivate is unavailable on chrome://extensions'
                    );
                  }

                  if (updateProfileMode) {
                    await chrome.developerPrivate.updateProfileConfiguration({
                      inDeveloperMode: enabled,
                    });
                  }

                  let infos;
                  if (extensionIds === null) {
                    infos = await chrome.developerPrivate.getExtensionsInfo({
                      includeDisabled: true,
                      includeTerminated: true,
                    });
                  } else {
                    infos = [];
                    for (const extensionId of extensionIds) {
                      try {
                        infos.push(await chrome.developerPrivate.getExtensionInfo(extensionId));
                      } catch {
                        // The extension may have disappeared between installation/removal events.
                      }
                    }
                  }

                  const eligible = infos.filter(
                    info => info?.userScriptsAccess?.isEnabled === true
                  );
                  const extensions = [];
                  for (const info of eligible) {
                    const extensionId = info.id;
                    try {
                      await chrome.developerPrivate.updateExtensionConfiguration({
                        extensionId,
                        userScriptsAccess: enabled,
                      });
                      await chrome.developerPrivate.reload(extensionId, {
                        failQuietly: true,
                      });
                      extensions.push({
                        id: extensionId,
                        userScriptsAccess: enabled,
                        ok: true,
                      });
                    } catch (error) {
                      extensions.push({
                        id: extensionId,
                        userScriptsAccess: enabled,
                        ok: false,
                        error: String(error),
                      });
                    }
                  }

                  const profile = updateProfileMode
                    ? await chrome.developerPrivate.getProfileConfiguration()
                    : null;
                  return {
                    inDeveloperMode: profile?.inDeveloperMode ?? null,
                    extensions,
                    eligibleExtensionIds: eligible.map(info => info.id),
                  };
                }
                """
