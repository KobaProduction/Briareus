"""One native developer-state observation with owner-scoped temporary page lifetime."""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Protocol

from web_runtime.application.developer_sync import ManagedExtensionState, ReconcileDeveloperSync
from web_runtime.browser_models import ChromiumDeveloperObservation, DeveloperSyncResult
from web_runtime.domain.developer_sync import (
    DeveloperSyncViolation,
    ExtensionFailure,
    ExtensionSyncReport,
)

from .browser_errors import BrowserError

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext, Page


class BrowserDeveloperOwner(ManagedExtensionState, Protocol):
    async def _ensure_started(self) -> BrowserContext: ...

    def _require_tab_capacity(self) -> None: ...

    def _register_page(self, page: Page) -> str: ...

    def _forget_page(self, page_id: str) -> None: ...


async def synchronize_developer_state(
    owner: BrowserDeveloperOwner,
    enabled: bool,
    *,
    extension_ids: list[str] | None = None,
    update_profile_mode: bool = True,
    context: BrowserContext | None = None,
) -> DeveloperSyncResult:
    context = context or await owner._ensure_started()
    owner._require_tab_capacity()
    page = await context.new_page()
    page_id = owner._register_page(page)
    try:
        await page.goto("chrome://extensions/", wait_until="domcontentloaded")
        requested_ids = (
            None if extension_ids is None else [value for value in extension_ids if value]
        )
        result = await page.evaluate(
            """
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
                """,
            {
                "enabled": enabled,
                "extensionIds": requested_ids,
                "updateProfileMode": update_profile_mode,
            },
        )
    except Exception as exc:
        raise BrowserError(f"Chromium developer-mode synchronization failed: {exc}") from exc
    finally:
        with contextlib.suppress(Exception):
            await page.close()
        owner._forget_page(page_id)

    try:
        observed = ChromiumDeveloperObservation.model_validate(result)
    except ValueError as exc:
        raise BrowserError("Invalid Chromium developer-state observation") from exc
    report = ExtensionSyncReport(
        frozenset(observed.eligible_extension_ids),
        tuple(
            ExtensionFailure(item.id, item.error or "unknown error")
            for item in observed.extensions
            if not item.ok
        ),
    )
    try:
        count = ReconcileDeveloperSync(owner).execute(
            report,
            tuple(extension_ids) if extension_ids is not None else None,
        )
    except DeveloperSyncViolation as exc:
        raise BrowserError(str(exc)) from exc
    return DeveloperSyncResult(
        in_developer_mode=observed.in_developer_mode,
        user_scripts_enabled=enabled,
        user_scripts_extension_count=count,
        extensions=observed.extensions,
    )
