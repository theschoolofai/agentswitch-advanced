import os, json, uuid, requests

def _url(): return os.environ["AGENTSWITCH_BASE_URL"].rstrip("/") + "/api/mcp"
def _hdr(): return {"Authorization": f"Bearer {os.environ['AGENTSWITCH_TOKEN']}",
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream"}

def rpc(method, params):
    body = {"jsonrpc":"2.0","id":str(uuid.uuid4()),"method":method,"params":params}
    r = requests.post(_url(), headers=_hdr(), data=json.dumps(body), timeout=60)
    r.raise_for_status()
    d = r.json()
    if "error" in d: raise RuntimeError(f"MCP error: {d['error']}")
    return d["result"]

def list_tools():
    return rpc("tools/list", {})["tools"]

def search(query, **kw):
    res = rpc("tools/call", {"name":"tools.search","arguments":{"query":query, **kw}})
    return res.get("structuredContent", res)

def call(name, arguments):
    res = rpc("tools/call", {"name":name,"arguments":arguments})
    return res.get("structuredContent", res)
