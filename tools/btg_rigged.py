#!/usr/bin/env python3
"""BIONICLE: The Game (2003, PC) rigged character extractor.

Usage: python btg_rigged.py <path-to-game>/Data <output-folder>
Needs: Python 3.8+, numpy, Pillow. Single-file bundle of btg_rigged.py + rig/*.py.

Reads the .vol archives read-only and writes, for every skinned entity:
  <out>/characters/<name>__<hash>.gltf   mesh + skeleton + per-vertex weights + animation clips
  <out>/characters.csv                   source file, bone/clip/mesh counts per output
Animations carry bone rotations and translations, including root motion.
"""

# ==== argz.py ====
import struct
def dec(src,ip,end):
    out=bytearray()
    while ip<end:
        c=src[ip]
        if c>=0x80:
            b=src[ip+1]; ip+=2
            w=(c<<8)|b
            if w&0x8000: w-=0x10000
            dist=1-(w>>4)
            n=(b&0xf)+2
            s=len(out)-dist
            for i in range(n): out.append(out[s+i])
        elif c<0x40:
            out+=src[ip+1:ip+2+c]; ip+=c+2
        else:
            out+=bytes([src[ip+1]])*(c-0x3e); ip+=2
    return bytes(out)
def bigb(d):
    A,B_,C,D,E,F=struct.unpack_from('<6I',d,0x78)
    p=0x190
    main=dec(d,p,p+E); rel=dec(d,p+E,p+E+F)
    return dict(A=A,B=B_,C=C,D=D,main=main,rel=rel)

# ==== objs.py ====
import struct
def objects(rel):
    v=struct.unpack('<%dI'%(len(rel)//4),rel)
    objs=[];cur=None
    for x in v:
        if x&0x80000000: cur=[x&0x7fffffff,[]]; objs.append(cur)
        else: cur[1].append(x)
    return objs

# ==== volt.py ====
import struct,sys
def parse(path):
    d=open(path,'rb').read(1<<20)
    mag,ver,n,nsz=struct.unpack_from('<4sIII',d,0)
    ents=[struct.unpack_from('<III',d,16+12*i) for i in range(n)]
    base=16+12*n
    out=[]
    for h,one,off in ents:
        p=base+off
        a,b,c,e=struct.unpack_from('<IIII',d,p)
        name=d[p+16:d.index(b'\0',p+16)].decode('latin1')
        out.append((name,a,b,c,e))
    return out

# ==== export.py ====
import sys,os,struct,json,io,collections
import numpy as np
from PIL import Image

def u32(m,o): return struct.unpack_from('<I',m,o)[0]

def cstr(m,o,n=32):
    s=m[o:o+n]; s=s.split(b'\0')[0]
    try: s=s.decode('ascii')
    except: return None
    return s if s and all(32<=ord(ch)<127 for ch in s) else None

def decode_tga(m,p):
    idl,cmt,it=m[p],m[p+1],m[p+2]
    cmfirst,cmlen=struct.unpack_from('<HH',m,p+3); cmd=m[p+7]
    w,h=struct.unpack_from('<HH',m,p+12); bpp=m[p+16]; desc=m[p+17]
    q=p+18+idl
    if it==1 and cmt==1 and bpp==8 and cmd in(24,32):
        nb=cmd//8
        pal=np.frombuffer(m,dtype=np.uint8,count=cmlen*nb,offset=q).reshape(cmlen,nb); q+=cmlen*nb
        pal=np.concatenate([np.zeros((cmfirst,nb),np.uint8),pal]) if cmfirst else pal
        if len(pal)<256: pal=np.concatenate([pal,np.zeros((256-len(pal),nb),np.uint8)])
        ix=np.frombuffer(m,dtype=np.uint8,count=w*h,offset=q).reshape(h,w)
        px=pal[ix]
    elif it==2 and bpp in(24,32):
        nb=bpp//8
        px=np.frombuffer(m,dtype=np.uint8,count=w*h*nb,offset=q).reshape(h,w,nb)
    else:
        return None
    rgb=px[...,[2,1,0]+([3] if px.shape[2]==4 else [])]
    if not desc&0x20: rgb=rgb[::-1]
    return Image.fromarray(np.ascontiguousarray(rgb),'RGBA' if rgb.shape[2]==4 else 'RGB')

class Pack:
    def __init__(s,main,rel):
        s.m=main; s.O=objects(rel)
        s.start={ps[0]:t for t,ps in s.O if ps}
    def tga(s,texobj):
        m=s.m
        t=s.start.get(texobj)
        if t==7:
            lst=u32(m,texobj+0x10); texobj=u32(m,lst); t=s.start.get(texobj)
        if t!=1: return None
        p=u32(m,texobj+0x10)
        return decode_tga(m,p)
    def batches(s):
        m=s.m
        for t,ps in s.O:
            if t not in (0x20,0x21,0x22): continue
            b=ps[0]
            fvf=u32(m,b+4); vbo=u32(m,b+0xc); tex=u32(m,b+0x10); di=u32(m,b+0x38)
            prim,nv,pc,node=struct.unpack_from('<4I',m,di)
            minidx,startidx=struct.unpack_from('<2I',m,di+0x20)
            yield dict(off=b,fvf=fvf,vb=vbo,tex=tex,prim=prim,nv=nv,pc=pc,node=node,min=minidx,start=startidx)
    def vb(s,o):
        m=s.m
        vt,a,stride,vc,vp,ic,ip=struct.unpack_from('<7I',m,o)
        raw=np.frombuffer(m,dtype=np.uint8,count=vc*stride,offset=vp).reshape(vc,stride)
        idx=np.frombuffer(m,dtype='<u2',count=ic,offset=ip)
        return stride,raw,idx

def mat2quat(R):
    # R: column-vector rotation matrix
    tr=R[0,0]+R[1,1]+R[2,2]
    if tr>0:
        S_=np.sqrt(tr+1.0)*2; w=0.25*S_; x=(R[2,1]-R[1,2])/S_; y=(R[0,2]-R[2,0])/S_; z=(R[1,0]-R[0,1])/S_
    elif R[0,0]>R[1,1] and R[0,0]>R[2,2]:
        S_=np.sqrt(1.0+R[0,0]-R[1,1]-R[2,2])*2; w=(R[2,1]-R[1,2])/S_; x=0.25*S_; y=(R[0,1]+R[1,0])/S_; z=(R[0,2]+R[2,0])/S_
    elif R[1,1]>R[2,2]:
        S_=np.sqrt(1.0+R[1,1]-R[0,0]-R[2,2])*2; w=(R[0,2]-R[2,0])/S_; x=(R[0,1]+R[1,0])/S_; y=0.25*S_; z=(R[1,2]+R[2,1])/S_
    else:
        S_=np.sqrt(1.0+R[2,2]-R[0,0]-R[1,1])*2; w=(R[1,0]-R[0,1])/S_; x=(R[0,2]+R[2,0])/S_; y=(R[1,2]+R[2,1])/S_; z=0.25*S_
    q=np.array([x,y,z,w]); return q/np.linalg.norm(q)

def decompose(M):
    # M: row-vector 4x4 (translation in last row)
    t=[float(x) for x in M[3,:3]]
    R=M[:3,:3].T.copy()
    sc=np.linalg.norm(R,axis=0); sc[sc==0]=1; R/=sc
    if np.linalg.det(R)<0: R[:,2]*=-1; sc[2]*=-1
    return t,[float(x) for x in mat2quat(R)],[float(x) for x in sc]

def strip_to_tris(ix):
    tris=[]
    for i in range(len(ix)-2):
        a,b,c=ix[i],ix[i+1],ix[i+2]
        if a==b or b==c or a==c: continue
        tris.append((a,b,c) if i%2==0 else (b,a,c))
    return tris

def node_groups(P):
    m=P.m; groups=collections.OrderedDict()
    for bt in P.batches():
        if bt['prim']!=5: continue
        groups.setdefault(bt['node'],[]).append(bt)
    out=collections.OrderedDict()
    for n,b in groups.items():
        nm=cstr(m,n+0x20) if n+0x40<len(m) else None
        out[(n,nm or 'node_%x'%n)]=b
    return out

def export(main_path,rel_path,outdir,name):
    P=Pack(open(main_path,'rb').read(),open(rel_path,'rb').read())
    g=node_groups(P)
    return write_gltf(P,[(nm,b) for (n,nm),b in g.items()],outdir,name)

def write_gltf(P,groups,outdir,name,texcache=None,skin=None,anims=None):
    m=P.m
    vbcache={}
    os.makedirs(outdir,exist_ok=True)
    texdir=os.path.join(outdir,'textures'); os.makedirs(texdir,exist_ok=True)
    texmap={}
    if texcache is None: texcache={}
    gl=dict(asset=dict(version='2.0',generator='bionicle-extract'),scenes=[dict(nodes=[])],scene=0,nodes=[],meshes=[],accessors=[],bufferViews=[],buffers=[],materials=[],textures=[],images=[],samplers=[dict(magFilter=9729,minFilter=9987,wrapS=10497,wrapT=10497)])
    binbuf=bytearray()
    def add_view(data,target=None):
        while len(binbuf)%4: binbuf.append(0)
        off=len(binbuf); binbuf.extend(data)
        bv=dict(buffer=0,byteOffset=off,byteLength=len(data))
        if target: bv['target']=target
        gl['bufferViews'].append(bv); return len(gl['bufferViews'])-1
    def add_acc(arr,ctype,typ,target=None,minmax=False,normalized=False):
        v=add_view(arr.tobytes(),target)
        a=dict(bufferView=v,componentType=ctype,count=int(arr.shape[0]),type=typ)
        if normalized: a['normalized']=True
        if minmax: a['min']=[float(x) for x in arr.min(0)]; a['max']=[float(x) for x in arr.max(0)]
        gl['accessors'].append(a); return len(gl['accessors'])-1
    def material(tex):
        if tex in texmap: return texmap[tex]
        if tex not in texcache:
            im=P.tga(tex) if tex!=0xffffffff else None
            fn=None
            if im is not None:
                if im.mode not in('RGB','RGBA'): im=im.convert('RGBA')
                if im.mode=='RGBA' and im.getextrema()[3][0]==255: im=im.convert('RGB')
                import hashlib
                fn='tex_%s.png'%hashlib.md5(im.tobytes()+im.mode.encode()+bytes(str(im.size),'ascii')).hexdigest()[:12]
                fp=os.path.join(texdir,fn)
                if not os.path.exists(fp): im.save(fp)
            texcache[tex]=(fn, im.mode if im is not None else None)
        fn,mode=texcache[tex]
        mat=dict(name='mat_%x'%tex,pbrMetallicRoughness=dict(metallicFactor=0.0,roughnessFactor=1.0),doubleSided=True)
        if fn is not None:
            gl['images'].append(dict(uri='textures/'+fn)); gl['textures'].append(dict(source=len(gl['images'])-1,sampler=0))
            mat['pbrMetallicRoughness']['baseColorTexture']=dict(index=len(gl['textures'])-1)
        gl['materials'].append(mat); texmap[tex]=len(gl['materials'])-1; return texmap[tex]
    stats=dict(nodes=0,tris=0,verts=0,batches=0)
    S=np.diag([1.,1.,-1.,1.])
    if skin is not None:
        bones=skin['bones']; nb=len(bones)
        base=len(gl['nodes'])
        for i,b in enumerate(bones):
            L=S@np.array(b['local']).reshape(4,4)@S
            t,r,sc=decompose(L)
            nd=dict(name=b['name'] or 'bone%d'%i,translation=t,rotation=r)
            if max(abs(x-1) for x in sc)>1e-3: nd['scale']=sc
            gl['nodes'].append(nd)
        orphans=[]
        for i,b in enumerate(bones):
            if i and b['parent']<nb and b['parent']!=i:
                gl['nodes'][base+b['parent']].setdefault('children',[]).append(base+i)
            elif i: orphans.append(base+i)
        IB=np.array([np.linalg.pinv(S@w@S) for w in skin['world']])
        IB[:,:3,3]=0; IB[:,3,3]=1; IB=IB.astype('<f4')
        iba=add_acc(IB.reshape(nb,16),5126,'MAT4')
        gl['skins']=[dict(name=name,joints=list(range(base,base+nb)),inverseBindMatrices=iba,skeleton=base)]
        gl['scenes'][0]['nodes'].append(base)
        if orphans:
            gl['nodes'].append(dict(name='Armature',children=[base]+orphans))
            gl['scenes'][0]['nodes'][-1]=len(gl['nodes'])-1
            gl['skins'][0]['skeleton']=len(gl['nodes'])-1
    for grp in groups:
        nm,bts=grp[0],grp[1]; jw=grp[2] if len(grp)>2 else None
        prims=[]
        for bt in bts:
            if bt['vb'] not in vbcache: vbcache[bt['vb']]=P.vb(bt['vb'])
            stride,raw,idx=vbcache[bt['vb']]
            n=bt['pc']+2
            ix=idx[bt['start']:bt['start']+n]
            if len(ix)<3 or ix.max()>=len(raw): continue
            tris=np.array(strip_to_tris(ix),dtype=np.int64)
            if len(tris)==0: continue
            used,inv=np.unique(tris,return_inverse=True)
            v=raw[used]
            pos=v[:,0:12].copy().view('<f4').reshape(-1,3).copy(); pos[:,2]*=-1
            attrs={}
            if stride==24:
                col=v[:,12:16][:,[2,1,0,3]].copy()  # BGRA->RGBA
                uv=v[:,16:24].copy().view('<f4').reshape(-1,2)
                attrs['COLOR_0']=add_acc(col.astype(np.uint8),5121,'VEC4',34962,normalized=True)
            else:
                nrm=v[:,12:24].copy().view('<f4').reshape(-1,3).copy(); nrm[:,2]*=-1
                ln=np.linalg.norm(nrm,axis=1,keepdims=True); ln[ln==0]=1; nrm=(nrm/ln).astype('<f4')
                uv=v[:,24:32].copy().view('<f4').reshape(-1,2)
                attrs['NORMAL']=add_acc(nrm,5126,'VEC3',34962)
            if not np.isfinite(pos).all(): continue
            attrs['POSITION']=add_acc(pos.astype('<f4'),5126,'VEC3',34962,minmax=True)
            attrs['TEXCOORD_0']=add_acc(np.ascontiguousarray(uv,dtype='<f4'),5126,'VEC2',34962)
            if skin is not None:
                J,Wt=jw(bt,used)
                attrs['JOINTS_0']=add_acc(J.astype('<u2'),5123,'VEC4',34962)
                attrs['WEIGHTS_0']=add_acc(Wt.astype('<f4'),5126,'VEC4',34962)
            tri=inv.reshape(-1,3)[:,[0,2,1]].astype('<u4')  # flip winding for Z mirror
            ia=add_acc(tri.reshape(-1),5125,'SCALAR',34963)
            prims.append(dict(attributes=attrs,indices=ia,material=material(bt['tex'])))
            stats['tris']+=len(tri); stats['verts']+=len(pos); stats['batches']+=1
        if not prims: continue
        gl['meshes'].append(dict(name=nm,primitives=prims))
        gl['nodes'].append(dict(name=nm,mesh=len(gl['meshes'])-1))
        if skin is not None: gl['nodes'][-1]['skin']=0
        gl['scenes'][0]['nodes'].append(len(gl['nodes'])-1); stats['nodes']+=1
    if not gl['meshes']: return None
    if anims: anims(gl,add_acc)
    for k in ('textures','images','materials'):
        if not gl[k]: del gl[k]
    if 'textures' not in gl: del gl['samplers']
    binname=name+'.bin'
    open(os.path.join(outdir,binname),'wb').write(binbuf)
    gl['buffers']=[dict(uri=binname,byteLength=len(binbuf))]
    json.dump(gl,open(os.path.join(outdir,name+'.gltf'),'w'))
    stats['textures']=len(gl.get('images',[]))
    return stats


# ==== skel.py ====
import re,struct,os,sys
PAT=re.compile(rb'\x00\x00\x00\x5a(....)\x00\x00\xff\x80\x04\x00\x5b\x00\x00\x00\x00\x5a(....)\x00\x00\xff\x80\x04\x00\x5c\x00',re.S)
def skeleton(m,h):
    n=u32(m,h); bones=u32(m,h+0x1c)
    if not (0<n<512) or bones+0xb0*n>len(m) or m[bones:bones+11]!=b'Scene Root\0': return None
    out=[]
    for i in range(n):
        r=bones+0xb0*i
        out.append(dict(name=m[r:r+16].split(b'\0')[0].decode('latin1'),parent=u32(m,r+0x18),
            local=struct.unpack_from('<16f',m,r+0x30)))
    return out
def links(m):
    res={}
    for mm in PAT.finditer(m):
        if mm.start()%4: continue
        ent,sk=struct.unpack('<I',mm.group(1))[0],struct.unpack('<I',mm.group(2))[0]
        if ent+8>len(m) or sk+0x40>len(m): continue
        node=u32(m,ent)
        if node<len(m) and skeleton(m,sk): res.setdefault(node,set()).add(sk)
    return res
SKOBJ=0x545a08
def find_skeletons(m):
    out={}
    for mm in re.finditer(b'Scene Root\x00',m):
        a=mm.start()
        for r in re.finditer(re.escape(struct.pack('<I',a)),m):
            h=r.start()-0x1c
            if h%4==0 and h>=0:
                s=skeleton(m,h)
                if s: out[h]=s
    return out
def skin_obj(m,node):
    cnt=u32(m,node+8)
    for o in range(node+0x50+4*cnt, node+0x50+4*cnt+0x20,4):
        if u32(m,o)==SKOBJ:
            nb,pl,pr,nv=struct.unpack_from('<4I',m,o+4)
            if nb<256 and pl<len(m) and pr<len(m):
                return dict(bones=list(struct.unpack_from('<%dH'%nb,m,pl)),rec=pr,nv=nv)
    return None
def vb_list(m,node):
    cnt=u32(m,node+8)
    return list(struct.unpack_from('<%dI'%cnt,m,node+0x50)) if cnt<256 else []
def batch_bone(m,bt):
    v=u32(m,bt['off']+0x3c)&0xffff
    return None if v==0xffff else v
def match_skeleton(m,node,name,skels,batches,L=None):
    so=skin_obj(m,node)
    need=max([batch_bone(m,b) or 0 for b in batches]+([max(so['bones'])] if so and so['bones'] else [0]))
    cands=[]
    if L and node in L: cands=[h for h in L[node] if h in skels]
    if not cands:
        cands=[h for h,s in skels.items() if any(b['name'][:15]==name[:15] for b in s)]
    cands=[h for h in cands if len(skels[h])>need]
    return cands[0] if cands else None

import numpy as np
def worlds(bones):
    n=len(bones); W=[None]*n
    def w(i):
        if W[i] is None:
            L=np.array(bones[i]['local']).reshape(4,4); p=bones[i]['parent']
            W[i]=L if (i==0 or p>=n or p==i) else L@w(p)
        return W[i]
    for i in range(n): w(i)
    return W

def node_binding(P,node,name,batches):
    # returns function giving (bone list per vertex) needs; and need/used bones for scoring
    m=P.m; so=skin_obj(m,node); vbl=vb_list(m,node)
    recs=None; offs={}
    if so and so['nv']:
        R=np.frombuffer(m,dtype=np.uint8,count=so['nv']*48,offset=so['rec']).reshape(-1,48)
        recs=(R[:,24:36].copy().view('<f4'),R[:,36:48].copy().view('<u4'))
        o=0
        for vb in vbl:
            if u32(m,vb+4)&0x80: offs[vb]=o; o+=u32(m,vb+12)
        if o!=so['nv']: recs=None
    return so,recs,offs

def make_jw(P,node,name,batches,bones):
    m=P.m; so,recs,offs=node_binding(P,node,name,batches)
    own=next((i for i,b in enumerate(bones) if b['name'][:15]==name[:15]),0)
    def jw(bt,used):
        n=len(used); J=np.zeros((n,4),np.uint16); Wt=np.zeros((n,4),np.float32)
        b=batch_bone(m,bt)
        if bt['vb'] in offs and recs is not None:
            w,ix=recs; r=offs[bt['vb']]+used
            J[:,:3]=np.array(so['bones'],dtype=np.int64)[np.minimum(ix[r],len(so['bones'])-1)]
            Wt[:,:3]=w[r]
            s=Wt.sum(1,keepdims=True); s[s==0]=1; Wt/=s
            Wt[Wt==0]=0; J[Wt==0]=0
        else:
            J[:,0]=b if b is not None and b<len(bones) else own; Wt[:,0]=1
        return J,Wt
    return jw

def fit_score(P,node,name,batches,bones):
    """mean distance from rigid-batch centroids to their bone segment (lower = better)"""
    m=P.m; W=worlds(bones); pos=[w[3,:3] for w in W]
    kids={}
    for i,b in enumerate(bones):
        if i: kids.setdefault(b['parent'],[]).append(i)
    jw=make_jw(P,node,name,batches,bones); d=[]
    for bt in batches:
        stride,raw,idx=P.vb(bt['vb']); ix=idx[bt['start']:bt['start']+bt['pc']+2]
        if len(ix)<3: continue
        used=np.unique(ix); J,Wt=jw(bt,used)
        if J.max()>=len(bones): return 1e9
        v=raw[used][:,:12].copy().view('<f4').reshape(-1,3)
        dom=J[np.arange(len(J)),Wt.argmax(1)]
        for j in np.unique(dom):
            c=v[dom==j].mean(0); segs=[pos[j]]+[pos[k] for k in kids.get(int(j),[])]
            best=min(np.linalg.norm(c-p) for p in segs)
            for k in kids.get(int(j),[]):
                a,bq=pos[j],pos[k]; ab=bq-a; t=np.clip(np.dot(c-a,ab)/max(np.dot(ab,ab),1e-9),0,1)
                best=min(best,np.linalg.norm(c-(a+t*ab)))
            d.append(best)
    return float(np.median(d)) if d else 1e9

ANIMVT=0x540ea8
def find_anims(m,skel_header):
    """Clip header: +4 name ptr, +0x10 id, +0x18 channel count, +0x1c ptr channel ids,
    +0x20 key count, +0x24 ptr key times (0..1), +0x2c ptr per-key rotation blocks,
    +0x30 ptr per-key translation blocks, +0x34 speed (clip length = 1/speed s).
    Channel id c drives bone c (c>=0, rotation + translation) or bone -c-1 (c<0, rotation only).
    Rotation block: int16 x,y,z,w per channel. Translation block: float xyz offsets added to the
    bone's bind translation (parent space); key 0 holds every channel, later keys only c>=0."""
    lo=u32(m,skel_header+8); hi=u32(m,skel_header+4); out=[]
    if not lo<hi<=lo+0x1000: hi=lo+1
    for mm in re.finditer(re.escape(struct.pack('<I',ANIMVT)),m):
        o=mm.start()
        if o%4 or not lo<=u32(m,o+4)<hi: continue
        nmp=u32(m,o+4); aname=m[nmp:nmp+32].split(b'\0')[0].decode('latin1')
        w=struct.unpack_from('<13I',m,o)
        nch,chp,nk,tp,dp,A,B=w[6],w[7],w[8],w[9],w[10],w[11],w[12]
        speed=struct.unpack_from('<f',m,o+0x34)[0]
        if not(0<nch<512 and 0<nk<100000) or max(chp+4*nch,tp+4*nk,A+4*nk,B+4*nk)>len(m): continue
        ch=np.frombuffer(m,dtype='<i4',count=nch,offset=chp)
        t=np.frombuffer(m,dtype='<f4',count=nk,offset=tp).astype(np.float64)
        dur=1.0/speed if speed>0 else 1.0
        q=np.empty((nk,nch,4)); tr=np.zeros((nk,nch,3))
        pos=np.nonzero(ch>=0)[0]
        for k in range(nk):
            a=u32(m,A+4*k)
            q[k]=np.frombuffer(m,dtype='<i2',count=nch*4,offset=a).reshape(nch,4)
            b=u32(m,B+4*k); n=nch if k==0 else len(pos)
            if b+12*n>len(m): break
            v=np.frombuffer(m,dtype='<f4',count=n*3,offset=b).reshape(n,3)
            if k==0: tr[:]=v
            else: tr[k,pos]=v
        else:
            q[:,:,:3]/=32767.0; q[:,:,3]/=1024.0
            out.append(dict(id=w[4],name=aname,channels=ch,times=t*dur,quats=q,trans=tr,addr=o))
    return out

def anim_writer(anims,bones,base_name):
    def bone_of(v): return v if v>=0 else -v-1
    def moved(an):
        return {bone_of(int(v)) for c,v in enumerate(an['channels'])
                if v>=0 or np.abs(an['trans'][0,c]).max()>1e-6}
    # bones translated by any clip get a translation track in every clip, so switching clips resets them
    tbones=sorted(b for an in anims for b in moved(an) if 0<b<len(bones))
    tbones=sorted(set(tbones))
    def f(gl,add_acc):
        joints=gl['skins'][0]['joints']
        gl['animations']=[]; used=set()
        for an in anims:
            samplers=[];channels=[]
            nk=len(an['times'])
            tin=add_acc(np.ascontiguousarray(an['times'],dtype='<f4').reshape(-1,1),5126,'SCALAR',minmax=True)
            tracks={}
            for c,v in enumerate(an['channels']):
                v=int(v)
                if v==-1: continue
                b=bone_of(v)
                if b<=0 or b>=len(bones): continue
                q=an['quats'][:,c,:].copy()
                n=np.linalg.norm(q,axis=1,keepdims=True); n[n==0]=1; q/=n
                q[:,0]*=-1; q[:,1]*=-1      # mirror Z: (x,y,z,w)->(-x,-y,z,w)
                for k in range(1,len(q)):   # keep hemisphere continuity
                    if np.dot(q[k],q[k-1])<0: q[k]*=-1
                out=add_acc(q.astype('<f4'),5126,'VEC4')
                samplers.append(dict(input=tin,output=out,interpolation='LINEAR'))
                channels.append(dict(sampler=len(samplers)-1,target=dict(node=joints[b],path='rotation')))
                tracks[b]=an['trans'][:,c,:]
            for b in tbones:
                t=np.array(bones[b]['local'][12:15])+tracks.get(b,np.zeros((nk,3)))
                t=np.broadcast_to(t,(nk,3)).copy(); t[:,2]*=-1   # mirror Z
                out=add_acc(t.astype('<f4'),5126,'VEC3')
                samplers.append(dict(input=tin,output=out,interpolation='LINEAR'))
                channels.append(dict(sampler=len(samplers)-1,target=dict(node=joints[b],path='translation')))
            nm=('anim_'+an['name']) if an['name'] else 'anim_%x'%an['id']
            base_nm=nm; k=2
            while nm in used: nm='%s_v%d'%(base_nm,k); k+=1
            used.add(nm)
            if channels: gl['animations'].append(dict(name=nm,samplers=samplers,channels=channels))
        if not gl['animations']: del gl['animations']
    return f

# ==== rigged.py ====
import sys,os,glob,hashlib,re,collections,csv

def rigged_nodes(P):
    m=P.m
    for (n,nm),b in node_groups(P).items():
        if skin_obj(m,n) is not None or any(batch_bone(m,x) is not None for x in b):
            yield n,nm,b

def assign(P,lib):
    m=P.m; local=find_skeletons(m); L=links(m)
    out={}; misses=[]
    for n,nm,b in rigged_nodes(P):
        stride,raw,idx=P.vb(b[0]['vb'])
        size=max(float(np.ptp(raw[:,:12].copy().view('<f4').reshape(-1,3),axis=0).max()),0.5)
        best=None
        def consider(cands):
            nonlocal best
            for key,s in cands:
                sc=fit_score(P,n,nm,b,s)
                if best is None or sc<best[0]: best=(sc,key,s)
        pre=[(('L',h),local[h]) for h in L.get(n,()) if h in local]
        consider(pre)
        if not best or best[0]>=0.2*size: consider([(('L',h),s) for h,s in local.items()])
        if not best or best[0]>=0.2*size: consider([(('G',k),s) for k,s in lib.items()])
        if best and best[0]<0.2*size:
            out.setdefault(best[1],(best[2],[]))[1].append((n,nm,b))
        else: misses.append(nm)
    return out,misses

def skel_key(s): return tuple((b['name'],b['parent']) for b in s)

def anim_hash(a):
    return hashlib.md5(a['quats'].tobytes()+a['trans'].tobytes()+a['times'].tobytes()+a['channels'].tobytes()).hexdigest()

def run(packs,outdir):
    packs=list(packs)
    lib={}; libanims={}
    for base,m,rel in packs:
        for h,s in find_skeletons(m).items():
            k=skel_key(s); lib.setdefault(k,s)
            for a in find_anims(m,h): libanims.setdefault(k,{}).setdefault(anim_hash(a),a)
    rows=[]; chars={}
    for base,m,rel in packs:
        P=Pack(m,rel)
        out,miss=assign(P,lib)
        for nm in miss: rows.append(dict(source=base,kind='unrigged',name=nm))
        for key,(s,nodes) in out.items():
            sk=skel_key(s)
            h=hashlib.md5(repr(sk).encode())
            for n,nm,b in nodes:
                for bt in b:
                    st_,raw,idx=P.vb(bt['vb']); ix=idx[bt['start']:bt['start']+bt['pc']+2]; h.update(raw[ix].tobytes())
            hd=h.hexdigest()
            title=max(nodes,key=lambda x:sum(b['pc'] for b in x[2]))[1]
            if hd in chars:
                rows.append(dict(source=base,kind='character(dup)',name=title,hash=hd)); continue
            chars[hd]=(P,nodes,s,sk,title)
            rows.append(dict(source=base,kind='character',name=title,hash=hd))
        print(base,flush=True)
    os.makedirs(outdir,exist_ok=True); done={}; tc={}
    for hd,(P,nodes,s,sk,title) in chars.items():
        fn='%s__%s'%(re.sub(r'[^A-Za-z0-9._-]+','_',title).strip('_') or 'unnamed',hd[:6])
        anims=sorted(libanims.get(sk,{}).values(),key=lambda a:(len(a['name']),a['name'],a['id']))
        names=collections.Counter()
        for a in anims:
            names[a['name']]+=1
            if names[a['name']]>1: a=dict(a); 
        jws=[(nm,b,make_jw(P,n,nm,b,s)) for n,nm,b in nodes]
        st=write_gltf(P,jws,outdir,fn,{},skin=dict(bones=s,world=worlds(s)),anims=anim_writer(anims,s,fn))
        if st: done[hd]=dict(output='characters/%s.gltf'%fn,bones=len(s),anims=len(anims),meshes=';'.join(x[1] for x in nodes),**st)
        print('wrote',fn,len(anims),flush=True)
    for r in rows:
        if r.get('hash') in done: r.update(done[r['hash']])
    return rows

# ==== main ====

import sys,os,glob,csv

def packs(data):
    for f in sorted(glob.glob(os.path.join(data,'*.vol'))):
        with open(f,'rb') as fh:
            for n,o,_,z,_ in parse(f):
                if '.PCS' not in n.upper(): continue
                fh.seek(o); d=fh.read(z)
                if d[:4]!=b'BIGB': continue
                b=bigb(d)
                yield os.path.basename(f).replace('.','_')+'_'+n, b['main'], b['rel']

def main():
    if len(sys.argv)!=3: print(__doc__); sys.exit(1)
    data,out=sys.argv[1],sys.argv[2]
    rows=run(packs(data),os.path.join(out,'characters'))
    keys=['source','kind','name','output','bones','anims','meshes','nodes','batches','verts','tris','textures']
    with open(os.path.join(out,'characters.csv'),'w',newline='') as fh:
        w=csv.DictWriter(fh,fieldnames=keys,extrasaction='ignore'); w.writeheader(); [w.writerow(r) for r in rows]
    print('done:',len(rows),'outputs')
if __name__=='__main__': main()

