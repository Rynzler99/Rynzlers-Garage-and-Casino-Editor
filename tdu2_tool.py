#!/usr/bin/env python3
r"""
TDU2 / Project Paradise 2 save tool  (decrypt - view - edit - re-encrypt - verify)

Pure Python 3, no extra packages. Works on PLAYERSAVE\DATA.
Cipher/format logic is ported from the open-source Project-Paradise-2/TDU2-Savegame-Editor.

USAGE (Windows: use "py" or "python"):
  py tdu2_tool.py export  "C:\...\savegame\Rynzler\PLAYERSAVE\DATA"
        -> writes DATA_fields.csv next to your DATA (open in Excel, edit the "value" column)
  py tdu2_tool.py apply   "C:\...\PLAYERSAVE\DATA"  "C:\...\DATA_fields.csv"
        -> writes DATA.new (your original is NOT touched). Verifies it. Shows every change.
  py tdu2_tool.py apply   DATA fields.csv --in-place
        -> same, but makes a timestamped backup first, then replaces DATA.
  py tdu2_tool.py set     DATA Driver.NbCoupon=100 Casino.money=939000000 [--in-place]
        -> change a few values directly (no CSV needed)
  py tdu2_tool.py presets               -> list the built-in casino presets
  py tdu2_tool.py preset  DATA vip-access [--in-place]   (also: casino-cosmetics, vip-car-flags)
  py tdu2_tool.py restore DATA [--latest]  -> list backups, or put the newest one back
  py tdu2_tool.py verify  DATA          -> checks decrypt + all chunk checksums
  py tdu2_tool.py diff    DATA_A DATA_B -> lists every field that differs
Add  --profile NAME  if the profile folder name is not the profile name.
CLOSE THE GAME before applying changes. Only fixed-size numbers/flags are editable
(not text, and not adding/removing list entries).
"""
import sys, os, re, csv, struct, zlib, base64, shutil, time, argparse

KDF_TABLES_B64 = (
    "AQABAAAAAAAAAQABAAABAQABAAABAQABAQEAAQEAAAAAAAEAAAEAAQEBAAAAAAEBAQAAAQABAQAB"
    "AAEAAQEAAAAAAAEBAQEAAQAAAQEBAQABAAAAAAAAAQEAAQABAAAAAQEAAAAAAQEAAAAAAAAAAAEA"
    "AAABAQEBAQABAAAAAQEAAAEAAAEAAQEAAAAAAAAAAQEBAAAAAQABAAAAAQAAAAEBAQEBAQAAAAEB"
    "AAEAAAAAAQABAAAAAQEAAAEAAQABAQEAAAABAAABAQEAAQEAAQEBAQEBAAAAAQAAAQEBAAABAQAB"
    "AAABAQABAQEBAAEBAQABAQABAQEAAQAAAQEAAAABAQABAAABAQEAAQABAAEBAAEAAAEBAAABAAEB"
    "AQEAAAEBAQEAAQAAAQEBAAAAAQEBAAABAQAAAAEAAAAAAQEAAQAAAQEBAAABAAEBAQEA"
)
SP_TABLE_B64 = (
    "AIKAAAAAAAAAgAAAAoKAAAKAgAACggAAAgAAAACAAAAAAgAAAIKAAAKCgAAAAgAAAgKAAAKAgAAA"
    "AIAAAgAAAAICAAAAAoAAAAKAAACCAAAAggAAAICAAACAgAACAoAAAoAAAAIAgAACAIAAAoAAAAAA"
    "AAACAgAAAoIAAAAAgAAAgAAAAoKAAAIAAAAAgIAAAIKAAAAAgAAAAIAAAAIAAAKAgAAAgAAAAIIA"
    "AAIAgAAAAgAAAgAAAAICgAACggAAAoKAAAKAAAAAgIAAAgKAAAIAgAACAgAAAoIAAACCgAACAgAA"
    "AAKAAAACgAAAAAAAAoAAAACCAAAAAAAAAoCAABBACEAAQABAAEAAABBACAAAAAgAEAAAABAACEAQ"
    "QABAEAAAQBBACEAAQAhAAAAAQABAAEAAAAgAEAAAABAACEAAQAgAEAAIABBAAEAAAAAAAAAAQABA"
    "AAAQQAgAAAAIQBAACAAQAABAAAAAAABACAAQQAAAAEAIQAAACEAQQAAAAAAAABBACAAQAAhAAAAI"
    "ABBAAEAAAAhAAEAIQABAAAAAAAhAAEAAQBAAAAAQQAhAEEAIABAAAAAAQAAAAAAAQBBAAAAAQAhA"
    "AAAIABAAAEAQAAgAEEAAQBAAAEAQAAgAAEAIAAAAAAAAQABAEEAAAAAAAEAQAAhAEEAIQABACAAE"
    "AQAAAAEBBAAAAAAEAAEEAAEABAAAAAAEAQEAAAEABAQAAQAEAAAEBAAABAAAAQAEAQEEBAABAAAA"
    "AQQEAQAAAAAABAQAAAAAAQEEAAEAAAABAQAAAAEEBAABBAQBAQAEAQAEAAEBAAAAAQAEAQAEBAAA"
    "AAQBAQQAAQAAAAAABAABAQQAAAAEBAABAAQBAAAAAAEAAAEBBAABAAQAAAAAAAEAAAQAAQAEAQEE"
    "AAEABAQAAAQAAQAAAAAAAAQAAQQEAQAEAAABAAAAAAQEAQEEBAAAAAQBAQAAAQEABAAABAAAAQQE"
    "AQAEBAEAAAAAAQQEAQEABAAAAAQAAQQAAQEAABBAgEAQAIBAEACAQAAAAEAQQABAAECAAABAgAAQ"
    "AIAAAAAAABBAAAAQQABAEECAQAAAgAAAAABAAEAAAABAgAAAAIAAEAAAAABAAAAQQIBAAAAAAABA"
    "AAAQAIBAEAAAQABAgAAAAIBAEAAAQABAAAAQAABAEEAAQBBAgEAAAIBAAEAAAABAgAAQQABAEECA"
    "QAAAgAAAAAAAAAAAABBAAEAQAABAAEAAQABAgAAAAIAAEECAQBAAgEAQAIBAAAAAQBBAgEAAAIAA"
    "AACAABAAAAAAQIAAEACAQBBAAEAAQIAAEACAQBAAAAAAQAAAEECAQAAAAAAAQAAAEAAAQBBAAIAA"
    "AACAAAQBAAAEAYAAACEAAAQAgAAAAAAAACAAAAQBgAAEIAAABACAAAABgAAEIIAAACEAAAQhgAAE"
    "AAAAACAAAAABAAAEIAAABCAAAAAAgAAAIIAABCGAAAQhgAAAAQAABCGAAAAgAAAAAAAAACGAAAQB"
    "AAAAAQAAACGAAAQAAAAEAIAAACGAAAAAAAAAAQAAACAAAAQBgAAAIYAABCCAAAABAAAAIAAABCGA"
    "AAQBgAAEIIAAAAAAAAABAAAEIYAABCGAAAQAAAAAIYAABCEAAAQBAAAAAAAABCAAAAAhgAAEAIAA"
    "AAGAAAAgAAAEAAAAAAAAAAQggAAEAYAAACAIAAAQAAAgEAAgAAAIICAQAAAgEAgAAAAIICAQAAAg"
    "AAAgABAIICAAAAAgAAgAABAIACAAACAAEAAAABAIIAAAAAAAAAgAIAAIIAAQACAAAAAgIAAIIAAQ"
    "CAAAAAgAIBAIACAQAAAAAAggIAAAICAQCCAAAAAgIAAAICAQAAAAEAAgABAIAAAACAAgEAAgIAAI"
    "ICAQAAAgAAggAAAIAAAQAAAgAAAgABAAAAAQCCAAAAgAABAIICAQACAgAAAAIBAIICAAACAgEAAA"
    "AAAIACAQCAAAAAAgAAAAACAQCCAgAAAgAAAIACAACCAAEAAAAAAAICAQAAAAEAgAIAAIIAAQAAAQ"
    "AAEAEAIBBAACAAAAAAAEAAABBAACAQQQAAAEEAIBBBACAAAQAAAAAAABAAACAQAAAAAAAAIBABAC"
    "AQQAAAAEAAIBBBAAAQAQAAAEAAIBAAACAAAQAgAEEAIBABAAAAAQAgAEAAABBAAAAQQQAgAEEAAB"
    "AAAAAAAAAgAEEAAAAAACAAQQAAAAEAABBAACAQQAAgEAEAIBABACAQAAAAEAEAAAAAACAAQAAgAA"
    "EAAABBACAQQAAAEEEAAABBACAQQAAAEAAAIBBBACAAAQAgAEEAAAAAAAAQAAAAEEEAIAAAAAAQQQ"
    "AAAAEAIABAAAAQAAAgAEAAIABAAAAQAQACAIAAgACAAAAAACACAIAggAAAAIIAgACCAAAAAAAAAI"
    "IAACAAAAAgggCAIIAAgCAAAIAgggCAIAAAgAACAAAAAAAAIIIAAACAAIAAggCAAAAAgCACAAAgAg"
    "AAIIAAgCCCAIAAAAAAAAAAAAACAAAgggAAAIAAgACCAIAgAAAAIAIAgCAAAAAgAACAIIAAgAACAA"
    "AAAgAAIIAAgAACAIAgAACAAIIAAAACAAAAgAAAIIIAACCAAAAAgAAAIAIAgACAAAAAAgCAIIIAAC"
    "ACAAAAgAAAIIAAgACCAIAAgAAAAAIAgCCAAIAgAACAIAIAgAACAIAAAgAAIAAAAACAAIAgg="
)

PC2=[13,16,10,23,0,4,2,27,14,5,20,9,22,18,11,3,25,7,15,6,26,19,12,1,
     40,51,30,36,46,54,29,39,50,44,32,47,43,48,38,55,33,52,45,41,49,35,28,31]
SHIFTS=(1,1,2,2,2,2,2,2,1,2,2,2,2,2,2,1)
E=[31,0,1,2,3,4,3,4,5,6,7,8,7,8,9,10,11,12,11,12,13,14,15,16,
   15,16,17,18,19,20,19,20,21,22,23,24,23,24,25,26,27,28,27,28,29,30,31,0]
_k=base64.b64decode("".join(KDF_TABLES_B64)); KDF=[list(_k[i*56:(i+1)*56]) for i in range(6)]
_s=struct.unpack("<512I",base64.b64decode("".join(SP_TABLE_B64))); SP=[_s[i*64:(i+1)*64] for i in range(8)]
assert len(_k)==336

def key_schedule(k):
    C=list(k[:28]);D=list(k[28:56]);out=[]
    for r in range(16):
        s=SHIFTS[r];C=C[s:]+C[:s];D=D[s:]+D[:s];cd=C+D;out.append([cd[PC2[i]] for i in range(48)])
    return out
def F(R,sk):
    o=0
    for sb in range(8):
        b=sb*6
        c=((((R>>(31-E[b]))&1)^sk[b])<<5|(((R>>(31-E[b+1]))&1)^sk[b+1])<<4|
           (((R>>(31-E[b+2]))&1)^sk[b+2])<<3|(((R>>(31-E[b+3]))&1)^sk[b+3])<<2|
           (((R>>(31-E[b+4]))&1)^sk[b+4])<<1|(((R>>(31-E[b+5]))&1)^sk[b+5]))
        o^=SP[sb][c]
    return o
def enc_blk(L,R,sk):
    for r in range(15): L,R=R,L^F(R,sk[r])
    return (L^F(R,sk[15])),R
def dec_blk(L,R,sk):
    for r in range(15,0,-1): L,R=R,L^F(R,sk[r])
    return (L^F(R,sk[0])),R
def kdf(ks):
    bb=[0]*64;p=0
    for r in range(6):
        for i in range(8):
            if p<len(ks) and ks[p]!=0: c=ks[p];p+=1
            else: c=0
            for b in range(8): bb[i*8+b]^=(c>>(7-b))&1
        rk=key_schedule(KDF[r]);L=R=0
        for b in range(32):
            if bb[b]:L|=1<<(31-b)
            if bb[32+b]:R|=1<<(31-b)
        for q in range(15): L,R=R,L^F(R,rk[q])
        L^=F(R,rk[15])
        for b in range(32): bb[b]=(L>>(31-b))&1; bb[32+b]=(R>>(31-b))&1
    return key_schedule(bb[:56])
def rol(x,n): return ((x<<n)|(x>>(32-n)))&0xffffffff
def eden_sha1(ch):
    pd=bytearray(ch);bl=len(ch)*8;pd.append(0x80)
    while len(pd)%64!=56: pd.append(0)
    pd.extend(bl.to_bytes(8,'big'))
    h=[0x67452301,0xefcdab89,0x98badcfe,0x10325476,0xc3d2e1f0]
    for o in range(0,len(pd),64):
        blk=pd[o:o+64];W=[blk[i*4+3] for i in range(16)]
        for i in range(16,80): W.append(rol(W[i-3]^W[i-8]^W[i-14]^W[i-16],1))
        a,b,c,d,e=h
        for i in range(80):
            if i<20:f,k=(b&c)|((~b)&d),0x5a827999
            elif i<40:f,k=b^c^d,0x6ed9eba1
            elif i<60:f,k=(b&c)|(b&d)|(c&d),0x8f1bbcdc
            else:f,k=b^c^d,0xca62c1d6
            t=(rol(a,5)+f+e+k+W[i])&0xffffffff;e,d,c,b,a=d,c,rol(b,30),a,t
        h=[(x+y)&0xffffffff for x,y in zip(h,[a,b,c,d,e])]
    return b''.join(x.to_bytes(4,'big') for x in h)
def crc_bytes(name): return (zlib.crc32(name.encode('latin1'))&0xffff).to_bytes(8,'little')
def split_footer(b):
    fl=b[-1];n=2+8+fl+2+1;f=b[-n:]
    if f[:2]!=b'##' or f[-3:-1]!=b'##': raise ValueError("bad footer")
    return f,n
def keystr(c8,fn): return b' '*6+c8[:2]+b'PLAYERSAVE'+fn.encode('ascii')
def decrypt(raw,profile,fn="DATA"):
    footer,n=split_footer(raw);c8=crc_bytes(profile);sk=kdf(keystr(c8,fn));ct=raw[:-n]
    pL,pR=struct.unpack('>II',c8);out=bytearray()
    for i in range(len(ct)//8):
        cL,cR=struct.unpack_from('>II',ct,i*8);dL,dR=dec_blk(cL,cR,sk)
        out.extend(struct.pack('>II',dL^pL,dR^pR));pL,pR=cL,cR
    part,tot=struct.unpack('<II',bytes(out[:4])+bytes(out[8:12]))
    if tot>50_000_000 or tot==0: raise ValueError("wrong profile name or not a TDU2 save (bad header)")
    off=16;rem=tot;ch=[];bad=0
    while rem>0:
        cl=min(rem,4096);pl=(cl+7)&~7;d=bytes(out[off:off+cl]);off+=pl
        h=bytes(out[off:off+20]);off+=24
        if eden_sha1(d)!=h: bad+=1
        ch.append(d);rem-=cl
    if bad: raise ValueError(f"{bad} chunk checksum(s) invalid - file damaged or wrong profile name")
    return b''.join(ch),footer
def encrypt(data,profile,fn,footer):
    c8=crc_bytes(profile);sk=kdf(keystr(c8,fn));tot=len(data);part=tot%4096 or 4096
    pay=bytearray(struct.pack('<II',part,0)+struct.pack('<II',tot,0));o=0
    while o<tot:
        ch=data[o:o+4096];o+=len(ch);pay.extend(ch+b'\0'*(((len(ch)+7)&~7)-len(ch)));pay.extend(eden_sha1(ch)+b'\0'*4)
    pL,pR=struct.unpack('>II',c8);ct=bytearray()
    for i in range(len(pay)//8):
        a,b=struct.unpack_from('>II',pay,i*8);cL,cR=enc_blk(a^pL,b^pR,sk)
        ct.extend(struct.pack('>II',cL,cR));pL,pR=cL,cR
    return bytes(ct)+footer

TYPES={1:('bool','<B',1),2:('sint8','<b',1),3:('sint16','<h',2),4:('sint32','<i',4),5:('sint64','<q',8),
       6:('uint8','<B',1),7:('uint16','<H',2),8:('uint32','<I',4),9:('uint64','<Q',8),10:('float','<f',4),11:('double','<d',8)}
def fields(x):
    """Return ordered list of (path,typeid,abs_offset) for every fixed-size number/flag."""
    _,_,s0,s1,s2,rn,rt=struct.unpack('<7I',x[:28]);sec0=x[s0:s1]
    d1=struct.unpack(f'<{(s2-s1)//4}I',x[s1:s2]);sec2=x[s2:];res=[]
    def sym(o): e=sec0.find(b'\0',o);return sec0[o:e].decode('latin1')
    def walk(tid,offset,path):
        hdr=d1[tid];n=(hdr>>4)&0x7ff;cur=offset
        for f in range(n):
            dw0=d1[tid+2+f*2];dw1=d1[tid+2+f*2+1];name=sym(dw0&0x7fffffff)
            isarr=(dw1>>31)&1;t=dw1&0x3fffffff;p=f"{path}.{name}" if path else name
            if isarr:
                cnt,ao=struct.unpack_from('<II',sec2,cur);cur+=8;eh=d1[t];et=eh&0xf;es=(eh>>15)&0x1ffff
                if et==0:
                    for k in range(cnt): walk(t,ao+k*es,f"{p}[{k}]")
                elif et in TYPES:
                    for k in range(cnt): res.append((f"{p}[{k}]",et,s2+ao+k*es))
            else:
                th=d1[t];tt=th&0xf
                if tt==0: walk(t,cur,p);cur+=(th>>15)&0x1ffff
                elif tt==12: cur+=4
                elif tt==13: cur+=8
                else:
                    res.append((p,tt,s2+cur));cur+=(th>>15)&0x1ffff
    walk(rt,0,"");return res
def rawval(x,tt,off):
    n,fmt,sz=TYPES[tt];v=struct.unpack_from(fmt,x,off)[0]
    return ('%.9g'%v) if tt in(10,11) else str(v)
def parse(tt,text):
    n,fmt,sz=TYPES[tt];t=text.strip()
    if tt==1:
        t={'true':'1','false':'0'}.get(t.lower(),t)
        v=int(t)
        if v not in(0,1): raise ValueError("true/false fields only accept 0/1/True/False")
        return struct.pack('<B',v)
    try:
        if tt in(10,11): return struct.pack(fmt,float(t))
        v=int(float(t)) if re.fullmatch(r'-?\d+\.0+',t) else int(t)
    except ValueError: raise ValueError(f"'{t}' is not a valid number")
    try: return struct.pack(fmt,v)
    except struct.error: raise ValueError(f"{v} is out of range for {n}")
def guess_profile(path,given):
    if given: return given
    p=os.path.abspath(path).split(os.sep)
    for i in range(len(p)-1):
        if p[i+1].upper()=='PLAYERSAVE': return p[i]
    sys.exit("Could not work out the profile name; use --profile NAME")
def load(path,profile):
    raw=open(path,'rb').read();pt,footer=decrypt(raw,profile,os.path.basename(path).upper() if os.path.basename(path).upper() in('DATA','KEYMAP','OPTIONS') else "DATA")
    return raw,pt,footer

def cmd_export(a):
    prof=guess_profile(a.data,a.profile);raw,pt,_=load(a.data,prof)
    out=a.out or os.path.join(os.path.dirname(os.path.abspath(a.data)),"DATA_fields.csv")
    rows=fields(pt)
    with open(out,'w',newline='',encoding='utf-8') as f:
        w=csv.writer(f);w.writerow(["path","type","value","offset"])
        for p,tt,off in rows: w.writerow([p,TYPES[tt][0],rawval(pt,tt,off),off])
    print(f"Profile {prof}: decrypted OK, all checksums valid. Wrote {len(rows)} fields -> {out}")
    print("Edit ONLY the 'value' column, save as CSV, then run the apply command.")
PRESETS={
 "vip-access":("VIP access: sets _vip_status and the VIP unlock bit (bit 54 of Casino.unlockables0), as the PP2 editor's 'Max Casino' does.",
   [("Casino.CasinoProgressionSave._vip_status","set",1),("Casino.unlockables0","orbit",54)]),
 "casino-cosmetics":("Casino cosmetics: cocktail, emote, clothes, shoes and glasses unlock masks (OR-ed in, nothing is removed).",
   [("Casino.CasinoProgressionSave._cocktail_unlock_flag","or",32767),("Casino.CasinoProgressionSave._emote_unlock_flag","or",4294967295),
    ("Casino.CasinoProgressionSave._cloth_bought","or",33554431),("Casino.CasinoProgressionSave._shoes_bought","or",63),
    ("Casino.CasinoProgressionSave._glasses_bought","or",15)]),
 "vip-car-flags":("Reward-car flags: marks the hall car and VIP car as seen/won. Does NOT add any car to your garage. Riskiest preset (same area as the original problem).",
   [("Casino.CasinoProgressionSave._hall_car_seen","set",1),("Casino.CasinoProgressionSave._hall_car_won","set",1),
    ("Casino.CasinoProgressionSave._vip_car_seen","set",1),("Casino.CasinoProgressionSave._vip_car_won","set",1)]),
}
def compute_edits(pt,edits):
    """edits: list of (path, kind, value) with kind in set/or/orbit/text. Returns (new_plaintext, [(path,before,after)])."""
    fl={p:(t,o) for p,t,o in fields(pt)};new=bytearray(pt);changes=[]
    for path,kind,val in edits:
        if path not in fl: raise ValueError(f"field not found in this save: {path}")
        tt,off=fl[path];cur=rawval(pt,tt,off)
        if kind=="text": b=parse(tt,str(val))
        else:
            c=int(float(cur)) if tt not in(10,11) else None
            if c is None: raise ValueError(f"{path}: bit operations need an integer field")
            v=int(val) if kind in("set","or") else (1<<int(val))
            nv=v if kind=="set" else (c|v)
            b=parse(tt,str(nv))
        if bytes(new[off:off+len(b)])==b: continue
        new[off:off+len(b)]=b;changes.append((path,cur,rawval(bytes(new),tt,off)))
    return bytes(new),changes
def commit(a,prof,footer,new,changes):
    """Encrypt, verify, show changes, write DATA.new (default) or back up + replace (--in-place)."""
    newb=encrypt(new,prof,"DATA",footer);chk,_=decrypt(newb,prof,"DATA")
    if chk!=new: sys.exit("Verification FAILED - nothing written.")
    print(f"{len(changes)} change(s):")
    for p,o,n in changes: print(f"  {p}: {o} -> {n}")
    if getattr(a,"in_place",False):
        bak=a.data+".backup-"+time.strftime("%Y%m%d-%H%M%S");shutil.copy2(a.data,bak)
        tmp=a.data+".tmp";open(tmp,'wb').write(newb);os.replace(tmp,a.data)
        print(f"Backup: {bak}\nWrote: {a.data}")
    else:
        o=a.data+".new";open(o,'wb').write(newb);print(f"Wrote: {o}  (original untouched; back it up, then rename .new to DATA)")
    print("Verified: decrypts cleanly, all chunk checksums valid, only the listed fields changed.")
def cmd_apply(a):
    prof=guess_profile(a.data,a.profile);raw,pt,footer=load(a.data,prof);edits=[]
    with open(a.csv,newline='',encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            if r['value'].strip()!="": edits.append((r['path'],"text",r['value']))
    fl={p:(t,o) for p,t,o in fields(pt)}
    edits=[e for e in edits if e[0] not in fl or e[2].strip()!=rawval(pt,*fl[e[0]])]   # skip untouched rows
    for e in edits:
        if e[0] not in fl: sys.exit(f"Unknown field in CSV: {e[0]}")
    if not edits: print("No changes found in the CSV - nothing to do.");return
    try: new,changes=compute_edits(pt,edits)
    except ValueError as ex: sys.exit(str(ex))
    if not changes: print("No effective changes - nothing to do.");return
    commit(a,prof,footer,new,changes)
def cmd_set(a):
    prof=guess_profile(a.data,a.profile);raw,pt,footer=load(a.data,prof);edits=[]
    for kv in a.pairs:
        if "=" not in kv: sys.exit(f"Use PATH=VALUE, got: {kv}")
        p,v=kv.split("=",1);edits.append((p.strip(),"text",v.strip()))
    try: new,changes=compute_edits(pt,edits)
    except ValueError as ex: sys.exit(str(ex))
    if not changes: print("Those values are already set - nothing to do.");return
    commit(a,prof,footer,new,changes)
def cmd_presets(a):
    for k,(d,e) in PRESETS.items():
        print(f"{k}\n   {d}")
        for p,kind,v in e: print(f"     {p}  {kind} {v}")
def cmd_preset(a):
    if a.name not in PRESETS: sys.exit("Unknown preset. Choose: "+", ".join(PRESETS))
    prof=guess_profile(a.data,a.profile);raw,pt,footer=load(a.data,prof)
    try: new,changes=compute_edits(pt,PRESETS[a.name][1])
    except ValueError as ex: sys.exit(str(ex))
    if not changes: print("Everything in this preset is already set - nothing to do.");return
    print(PRESETS[a.name][0]);commit(a,prof,footer,new,changes)
def list_backups(path):
    d=os.path.dirname(os.path.abspath(path));b=os.path.basename(path)
    return sorted(os.path.join(d,f) for f in os.listdir(d) if f.startswith(b+".backup-"))
def cmd_restore(a):
    bs=list_backups(a.data)
    if not bs: sys.exit("No backups found next to this file.")
    if not a.latest:
        print("Backups (oldest first):"); [print("  ",x) for x in bs]; print("Run again with --latest to restore the newest one."); return
    src=bs[-1];prof=guess_profile(a.data,a.profile);decrypt(open(src,'rb').read(),prof,"DATA")   # must be a valid save
    safety=a.data+".before-restore-"+time.strftime("%Y%m%d-%H%M%S");shutil.copy2(a.data,safety)
    shutil.copy2(src,a.data);print(f"Restored {src}\nYour previous file was kept as {safety}")
def cmd_verify(a):
    prof=guess_profile(a.data,a.profile);raw,pt,_=load(a.data,prof)
    print(f"OK: profile {prof}, {len(pt)} bytes of data, all chunk checksums valid, "+("re-encrypts byte-identically." if encrypt(pt,prof,"DATA",split_footer(raw)[0])==raw else "re-encrypt differs (unexpected)."))
def cmd_diff(a):
    prof=guess_profile(a.a,a.profile);_,pa,_=load(a.a,prof);_,pb,_=load(a.b,prof)
    fa={p:rawval(pa,tt,o) for p,tt,o in fields(pa)};fb={p:rawval(pb,tt,o) for p,tt,o in fields(pb)}
    n=0
    for p in sorted(set(fa)|set(fb)):
        if fa.get(p)!=fb.get(p): n+=1;print(f"{p}: {fa.get(p,'<absent>')}  ->  {fb.get(p,'<absent>')}")
    print(f"{n} differing fields (lists that changed length show as added/absent entries).")
if __name__=="__main__":
    ap=argparse.ArgumentParser(description="TDU2 save tool");ap.add_argument("--profile")
    sp=ap.add_subparsers(dest="cmd",required=True)
    e=sp.add_parser("export");e.add_argument("data");e.add_argument("-o","--out");e.add_argument("--profile",dest="profile")
    p=sp.add_parser("apply");p.add_argument("data");p.add_argument("csv");p.add_argument("--in-place",action="store_true");p.add_argument("--profile",dest="profile")
    s_=sp.add_parser("set");s_.add_argument("data");s_.add_argument("pairs",nargs="+");s_.add_argument("--in-place",action="store_true");s_.add_argument("--profile",dest="profile")
    sp.add_parser("presets")
    pr=sp.add_parser("preset");pr.add_argument("data");pr.add_argument("name");pr.add_argument("--in-place",action="store_true");pr.add_argument("--profile",dest="profile")
    rs=sp.add_parser("restore");rs.add_argument("data");rs.add_argument("--latest",action="store_true");rs.add_argument("--profile",dest="profile")
    v=sp.add_parser("verify");v.add_argument("data");v.add_argument("--profile",dest="profile")
    d=sp.add_parser("diff");d.add_argument("a");d.add_argument("b");d.add_argument("--profile",dest="profile")
    a=ap.parse_args()
    try: {"export":cmd_export,"apply":cmd_apply,"set":cmd_set,"presets":cmd_presets,"preset":cmd_preset,"restore":cmd_restore,"verify":cmd_verify,"diff":cmd_diff}[a.cmd](a)
    except (ValueError,OSError) as ex: sys.exit(f"Error: {ex}")
