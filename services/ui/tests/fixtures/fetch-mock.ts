type FetchHandler=(...args:Parameters<typeof fetch>)=>ReturnType<typeof fetch>
const nativeFetch=globalThis.fetch

/** Retain Bun's static fetch contract while replacing only the request handler. */
export function fetchMock(handler:FetchHandler):typeof fetch {
  return Object.assign(handler,{preconnect:nativeFetch.preconnect})
}
