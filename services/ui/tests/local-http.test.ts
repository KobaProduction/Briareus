import { describe, expect, it } from "bun:test"
import { localHttpProxy,LOCAL_GATEWAY_URL,LOCAL_GATEWAY_HOST } from "../local-http-proxy"
import { needsApprovedHttpCallback } from "../src/shared/lib/local-http-auth"

describe("explicit native HTTP Frontend transport",()=>{
  it("never installs an implicit API proxy",()=>{
    expect(localHttpProxy(undefined)).toBeUndefined()
    expect(localHttpProxy("")).toBeUndefined()
  })
  it("only proxies API and its live events endpoint to the existing native loopback Gateway",()=>{
    const source=localHttpProxy("gateway")
    if(!source)throw new Error("Expected explicit local proxy")
    expect(Object.keys(source)).toEqual(["/api/v1/events","/api/"])
    expect(source["/api/v1/events"]).toMatchObject({target:LOCAL_GATEWAY_URL,changeOrigin:false,ws:true,timeout:0,proxyTimeout:0,headers:{host:LOCAL_GATEWAY_HOST}})
    expect(source["/api/"]?.target).toBe(LOCAL_GATEWAY_URL)
    expect(source["/api/"]?.target).toBe("http://127.0.0.1:18925")
    expect(source["/api/"]?.headers).toEqual({host:LOCAL_GATEWAY_HOST})
    expect(source["/api/"]?.changeOrigin).toBe(false)
  })
  it("cannot be pointed to public Dev or an arbitrary private transport",()=>{
    for(const input of ["https://briareus.koba-nexus.ru","http://127.0.0.1:18928","backend","1","false","all"]){
      expect(()=>localHttpProxy(input)).toThrow()
    }
  })
  it("does not silently enable a live OAuth redirect on unapproved HTTP loopback",()=>{
    for(const hostname of ["127.0.0.1","localhost"]){
      expect(needsApprovedHttpCallback({hostname,protocol:"http:"})).toBe(true)
    }
    expect(needsApprovedHttpCallback({hostname:"briareus.koba-nexus.ru",protocol:"https:"})).toBe(false)
    expect(needsApprovedHttpCallback({hostname:"127.0.0.1",protocol:"https:"})).toBe(false)
    expect(needsApprovedHttpCallback({hostname:"192.168.1.2",protocol:"http:"})).toBe(false)
  })
})
