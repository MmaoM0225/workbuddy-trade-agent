#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pull_all_fund_nav.py - 一次性拉齐宽基+行业全部可买基金的复权净值"""
import json, os, sys, time, urllib.request
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "warehouse", "fund_nav")

class Mcp:
    def __init__(self, url, headers):
        self.url, self.headers = url, dict(headers); self.sid=None; self._id=0
        self.headers.update({"Content-Type":"application/json","Accept":"application/json, text/event-stream"})
    def _post(self,p):
        req=urllib.request.Request(self.url,data=json.dumps(p).encode(),headers=self.headers,method="POST")
        if self.sid: req.add_header("Mcp-Session-Id",self.sid)
        with urllib.request.urlopen(req,timeout=180) as r:
            if r.headers.get("Mcp-Session-Id"): self.sid=r.headers["Mcp-Session-Id"]
            return r.read().decode(), r.headers.get("Content-Type","")
    def req(self,m,p):
        self._id+=1; raw,ct=self._post({"jsonrpc":"2.0","id":self._id,"method":m,"params":p})
        if "text/event-stream" in ct:
            obj=None
            for line in raw.splitlines():
                if line.startswith("data:"): obj=json.loads(line[5:].strip())
            return obj
        return json.loads(raw)
    def init(self):
        for v in ("2025-06-18","2025-03-26","2024-11-05"):
            if "error" not in self.req("initialize",{"protocolVersion":v,"capabilities":{},"clientInfo":{"name":"n","version":"1"}}):
                self._post({"jsonrpc":"2.0","method":"notifications/initialized"}); return
    def call(self,n,a,retries=3):
        last=None
        for i in range(retries):
            try:
                r=self.req("tools/call",{"name":n,"arguments":a})
                if "error" in r: raise RuntimeError(str(r["error"])[:150])
                res=r.get("result",{})
                t="".join(c.get("text","") for c in res.get("content",[]) if c.get("type")=="text")
                if res.get("isError"): raise RuntimeError(t[:150])
                return json.loads(t) if t else None
            except Exception as e:
                last=e; time.sleep(1.5*(i+1))
        raise RuntimeError(str(last)[:150])

def main():
    codes=set()
    u=json.load(open(os.path.join(ROOT,'data','index_universe.json'),encoding='utf-8'))
    for x in u['indices']:
        if x.get('of_fund'): codes.add(x['of_fund'])
    fm=json.load(open(os.path.join(ROOT,'data','industry_fund_map.json'),encoding='utf-8'))['map']
    for v in fm.values():
        p=v.get('primary')
        if p and p.get('venue') in ('场外','LOF'): codes.add(p['fund_code'])
    codes=sorted(codes)
    print('待拉净值 %d 只'%len(codes))
    cfg=json.loads(os.environ['CODEBUDDY_MCP_CONFIG']); s=cfg['mcpServers']['tushare']
    ts=Mcp(s['url'], s.get('headers',{})); ts.init()
    os.makedirs(OUT,exist_ok=True)
    ok,fail=0,[]
    for i,c in enumerate(codes,1):
        try:
            rows=ts.call('fund_nav',{'ts_code':c,'start_date':'20190101','end_date':'20261027',
                                     'fields':['ts_code','nav_date','unit_nav','adj_nav']}) or []
            data={}
            for r in rows:
                u=r.get('unit_nav'); a=r.get('adj_nav')
                if r.get('nav_date') and u: data[r['nav_date']]=(u,a)
            if not data:
                fail.append(c); print('[%d/%d] %-12s EMPTY'%(i,len(codes),c),flush=True); continue
            with open(os.path.join(OUT,c+'.csv'),'w',encoding='utf-8',newline='') as f:
                f.write('nav_date,unit_nav,adj_nav\n')
                for d in sorted(data):
                    u,a=data[d]
                    f.write('%s,%s,%s\n'%(d,u,a if a is not None else ''))
            ok+=1
            if i%20==0: print('[%d/%d] ok=%d'%(i,len(codes),ok),flush=True)
        except Exception as e:
            fail.append(c); print('[%d/%d] %s FAIL %s'%(i,len(codes),c,str(e)[:60]),flush=True)
        time.sleep(0.2)
    print('DONE ok=%d fail=%d'%(ok,len(fail)))
    if fail: print('fail codes:', fail[:12])

if __name__=='__main__': main()
