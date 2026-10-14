#!/usr/bin/env python3
"""BIONICLE: The Game (2003, PC) model extractor.

Usage: python btg_models.py <path-to-game>/Data <output-folder>
Needs: Python 3.8+, numpy, Pillow  (pip install numpy pillow)

Reads the .vol archives read-only, decompresses the BIGB level/entity files
(.PCM = level, .PCS/.PCSI = entities), and writes glTF 2.0 (.gltf + .bin + PNG textures):
  <out>/levels/<level>.gltf      whole level geometry, world space
  <out>/collision/<level>.gltf   the level's collision mesh, one material per surface type
  <out>/entities/<name>__<hash>.gltf   each entity mesh in bind pose, written once per game
  <out>/entities.csv             every unique entity mesh with the levels/sources that use it
  <out>/placements/<level>.gltf  where each strat (creature, pickup, prop, trigger, effect) is placed,
                                 as named empty nodes plus waypoint paths and trigger boxes (and .json)
  <out>/placements.csv           every placement in every level
  <out>/index.csv                which source file produced what
Format notes are in FORMAT_NOTES.md next to this script.
"""
import sys,os,glob,json,hashlib,re,collections,csv,struct,io,bisect
import numpy as np
from PIL import Image

# ---- BIGB decompression (algorithm from BIONICLE.exe @0x441fc0) ----
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

# ---- relocation table -> object list ----
def objects(rel):
    v=struct.unpack('<%dI'%(len(rel)//4),rel)
    objs=[];cur=None
    for x in v:
        if x&0x80000000: cur=[x&0x7fffffff,[]]; objs.append(cur)
        else: cur[1].append(x)
    return objs

# ---- mesh / texture decoding and glTF writer ----
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

BLEND_NAMES={(5,6):'alpha',(5,2):'additive'}
def blend_state(m,b):
    """Render states of a draw batch: +0x1C count, +0x20 ptr to (D3DRENDERSTATETYPE, value) pairs.
    27 ALPHABLENDENABLE, 19 SRCBLEND, 20 DESTBLEND, 15 ALPHATESTENABLE, 14 ZWRITEENABLE.
    Blend factors without an explicit ALPHABLENDENABLE=0 mean blending is on. +0x14 is the
    material colour (ARGB); its alpha is the batch opacity.
    +0x40 is a flag word: 0x400 (or 0x800) makes the game draw the batch with alpha test on
    (ALPHAREF 0xC0, or 0xFE) and then again without depth writes for the soft edges
    (BIONICLE.exe @0x449766), so a batch with no blend states of its own is a cutout."""
    cnt,p=struct.unpack_from('<2I',m,b+0x1c)
    rs={}
    if 0<cnt<64 and p+8*cnt<=len(m):
        v=struct.unpack_from('<%dI'%(2*cnt),m,p); rs=dict(zip(v[0::2],v[1::2]))
    src,dst=rs.get(19,5),rs.get(20,6)
    if rs.get(15)==1: mode='cutout'
    elif rs.get(27)==1 or (rs.get(27)!=0 and (19 in rs or 20 in rs)):
        mode=BLEND_NAMES.get((src,dst),'alpha' if dst!=2 else 'additive')
    elif u32(m,b+0x40)&0xc00: mode='cutout'
    else: mode='opaque'
    alpha=(u32(m,b+0x14)>>24)/255.0 if mode in('alpha','additive') else 1.0
    return (mode,rs.get(14,1)!=0,src,dst,round(alpha,4))

TEXOPS={1:'disable',2:'selectArg1',3:'selectArg2',4:'modulate',5:'modulate2x',6:'modulate4x',7:'add',
        8:'addSigned',9:'addSigned2x',10:'subtract',11:'addSmooth',12:'blendDiffuseAlpha',13:'blendTextureAlpha'}
def tex_layers(m,texobj,b):
    """Animated texture (relocation type 0x07): +0x0C layer count, +0x10 ptr to 0x40-byte layers:
    ptr texture, f32 scrollU, scrollV (UV units/s), rotate (rad/s), f32[4] tint, f32[3] unknown (wave?).
    Layer k>0 is combined onto the result by the colour op of texture stage k (batch +0x24 list);
    its D3DTEXTUREADDRESS U/V (1 wrap, 2 mirror, 3 clamp, 4 border) come from the sampler list (+0x2C)."""
    n,lp=struct.unpack_from('<2I',m,texobj+0xc)
    if not 0<n<9 or lp+0x40*n>len(m): return None
    c,p=struct.unpack_from('<2I',m,b+0x24); ops={}
    if 0<c<64 and p+12*c<=len(m):
        t=struct.unpack_from('<%dI'%(3*c),m,p)
        ops={t[i]:t[i+2] for i in range(0,3*c,3) if t[i+1]==1}
    c,p=struct.unpack_from('<2I',m,b+0x2c); addr={}
    if 0<c<64 and p+12*c<=len(m):
        t=struct.unpack_from('<%dI'%(3*c),m,p)
        for i in range(0,3*c,3):
            if t[i+1] in (1,2): addr[(t[i],t[i+1])]=t[i+2]
    out=[]
    for k in range(n):
        w=struct.unpack_from('<I15f',m,lp+0x40*k)
        out.append(dict(tex=w[0],op='base' if k==0 else TEXOPS.get(ops.get(k),'modulate'),
            scroll=[round(w[1],5),round(w[2],5)],rotate=round(w[3],5),tint=[round(x,4) for x in w[4:8]],
            params=[round(x,5) for x in w[8:11]],address=[addr.get((k,1),1),addr.get((k,2),1)]))
    if n==1 and not any(out[0]['scroll']) and not out[0]['rotate']: return None
    return out

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
            if t not in (0x20,0x21,0x22,0x26): continue  # 0x26: water surface batches
            b=ps[0]
            fvf=u32(m,b+4); vbo=u32(m,b+0xc); tex=u32(m,b+0x10); di=u32(m,b+0x38)
            prim,nv,pc,node=struct.unpack_from('<4I',m,di)
            minidx,startidx=struct.unpack_from('<2I',m,di+0x20)
            yield dict(off=b,bs=blend_state(m,b),fvf=fvf,vb=vbo,tex=tex,prim=prim,nv=nv,pc=pc,node=node,min=minidx,start=startidx)
    def vb(s,o):
        m=s.m
        vt,a,stride,vc,vp,ic,ip=struct.unpack_from('<7I',m,o)
        raw=np.frombuffer(m,dtype=np.uint8,count=vc*stride,offset=vp).reshape(vc,stride)
        idx=np.frombuffer(m,dtype='<u2',count=ic,offset=ip)
        return stride,raw,idx

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

def write_gltf(P,groups,outdir,name,texcache=None):
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
    def material(tex,bs=None,valpha=False,boff=None,vcol=False):
        if bs is not None and bs[0]=='alpha' and bs[4]>=1 and not valpha:
            im_mode=texcache[tex][1] if tex in texcache else None
            if tex not in texcache:
                im=P.tga(tex) if tex!=0xffffffff else None
                im_mode='RGBA' if im is not None and im.mode in('RGBA','LA','PA','P') and 'A' in im.getbands() and im.getextrema()[-1][0]<255 else 'RGB'
            if im_mode!='RGBA': bs=None   # blend state set, but nothing is see-through: keep it opaque
        layers=tex_layers(P.m,tex,boff) if boff is not None and P.start.get(tex)==7 else None
        key=(tex,bs if bs and bs[0]!='opaque' else None,tuple(l['op'] for l in layers) if layers else None,vcol)
        if key in texmap: return texmap[key]
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
        if bs is not None and bs[0]!='opaque':
            mode,zw,src,dst,alpha=bs
            mat['name']+='_'+mode
            if mode=='cutout': mat['alphaMode']='MASK'; mat['alphaCutoff']=0.5
            else:
                mat['alphaMode']='BLEND'
                # The game copies the material alpha into every vertex colour (checked on all 1,298
                # such batches), so only meshes without vertex colours need it as a factor.
                if alpha<1 and not vcol: mat['pbrMetallicRoughness']['baseColorFactor']=[1.0,1.0,1.0,alpha]
            mat['extras']=dict(btg=dict(blend=mode,depthWrite=zw,srcBlend=src,dstBlend=dst))
        if layers:
            for l in layers:
                im=P.tga(l['tex']); l['image']=None
                if im is not None:
                    if im.mode not in('RGB','RGBA'): im=im.convert('RGBA')
                    if im.mode=='RGBA' and im.getextrema()[3][0]==255: im=im.convert('RGB')
                    import hashlib
                    fn='tex_%s.png'%hashlib.md5(im.tobytes()+im.mode.encode()+bytes(str(im.size),'ascii')).hexdigest()[:12]
                    fp=os.path.join(texdir,fn)
                    if not os.path.exists(fp): im.save(fp)
                    l['image']='textures/'+fn
                del l['tex']
            mat.setdefault('extras',{}).setdefault('btg',{})['layers']=layers
        gl['materials'].append(mat); texmap[key]=len(gl['materials'])-1; return texmap[key]
    stats=dict(nodes=0,tris=0,verts=0,batches=0)
    for nm,bts in groups:
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
            tri=inv.reshape(-1,3)[:,[0,2,1]].astype('<u4')  # flip winding for Z mirror
            ia=add_acc(tri.reshape(-1),5125,'SCALAR',34963)
            prims.append(dict(attributes=attrs,indices=ia,material=material(bt['tex'],bt.get('bs'),bool(stride==24 and (v[:,15]<255).any()),bt['off'],stride==24)))
            stats['tris']+=len(tri); stats['verts']+=len(pos); stats['batches']+=1
        if not prims: continue
        gl['meshes'].append(dict(name=nm,primitives=prims))
        gl['nodes'].append(dict(name=nm,mesh=len(gl['meshes'])-1))
        gl['scenes'][0]['nodes'].append(len(gl['nodes'])-1); stats['nodes']+=1
    if not gl['meshes']: return None
    for k in ('textures','images','materials'):
        if not gl[k]: del gl[k]
    if 'textures' not in gl: del gl['samplers']
    binname=name+'.bin'
    open(os.path.join(outdir,binname),'wb').write(binbuf)
    gl['buffers']=[dict(uri=binname,byteLength=len(binbuf))]
    json.dump(gl,open(os.path.join(outdir,name+'.gltf'),'w'))
    stats['textures']=len(gl.get('images',[]))
    return stats


def collision(m):
    """Level collision mesh at the start of a .PCM (relocation type 0x10B): u32 size, u32 count,
    0, f32 centre[3], f32 radius^2, f32 radius; at 0x20 u32 offset (0x30), u32 record count, u32 count, 0.
    Records are 16 bytes, f32 x, y, z, u32 code, laid out as PS2-style triangle strips: bit 7 (0x80)
    adds the vertex to the strip, bit 6 (0x40) also draws a triangle with the two before it, bit 8
    (0x100) flips its winding, the top 16 bits are the surface type, and a record without bit 7 ends
    the strip. Returns (vertices, triangles, surface per triangle) or None."""
    if len(m)<0x40: return None
    cnt=u32(m,4); off,n,n1=struct.unpack_from('<3I',m,0x20)
    if off!=0x30 or n1!=cnt or not 0<n<=(len(m)-off)//16: return None
    A=np.frombuffer(m,dtype='<u4',count=n*4,offset=off).reshape(n,4)
    V=A[:,:3].copy().view('<f4'); code=A[:,3].tolist()
    tris=[]; surf=[]; a=b=None
    for i,k in enumerate(code):
        if not k&0x80: a=b=None; continue
        if k&0x40 and b is not None and a is not None:
            tris.append((b,a,i) if k&0x100 else (a,b,i)); surf.append(k>>16)
        a,b=b,i
    if not tris: return None
    return V,np.array(tris,np.int64),np.array(surf)

def write_collision(m,outdir,name):
    """One glTF per level with a primitive (and material surface_<type>) per surface type."""
    c=collision(m)
    if c is None: return None
    V,T,S=c; os.makedirs(outdir,exist_ok=True)
    used,inv=np.unique(T,return_inverse=True); P=V[used].astype('<f4').copy(); P[:,2]*=-1
    I=inv.reshape(-1,3)[:,[0,2,1]].astype('<u4')   # flip winding for the Z mirror
    gl=dict(asset=dict(version='2.0',generator='bionicle-extract'),scene=0,scenes=[dict(nodes=[0])],
            nodes=[dict(name=name+'_collision',mesh=0)],meshes=[dict(name=name+'_collision',primitives=[])],
            materials=[],accessors=[],bufferViews=[])
    buf=bytearray()
    def acc(a,ct,typ,tgt,count,minmax=False):
        while len(buf)%4: buf.append(0)
        gl['bufferViews'].append(dict(buffer=0,byteOffset=len(buf),byteLength=a.nbytes,target=tgt)); buf.extend(a.tobytes())
        d=dict(bufferView=len(gl['bufferViews'])-1,componentType=ct,count=count,type=typ)
        if minmax: d['min']=[float(x) for x in a.min(0)]; d['max']=[float(x) for x in a.max(0)]
        gl['accessors'].append(d); return len(gl['accessors'])-1
    pa=acc(P,5126,'VEC3',34962,len(P),True); counts={}
    for st in sorted(set(S.tolist())):
        h=hashlib.md5(b'%d'%st).digest()   # a stable colour per surface type
        gl['materials'].append(dict(name='surface_%d'%st,doubleSided=True,extras=dict(btg=dict(surface=st)),
            pbrMetallicRoughness=dict(baseColorFactor=[0.25+h[0]/340,0.25+h[1]/340,0.25+h[2]/340,1.0],metallicFactor=0.0,roughnessFactor=1.0)))
        ix=np.ascontiguousarray(I[S==st]).reshape(-1); counts[st]=len(ix)//3
        gl['meshes'][0]['primitives'].append(dict(attributes=dict(POSITION=pa),indices=acc(ix,5125,'SCALAR',34963,len(ix)),material=len(gl['materials'])-1))
    open(os.path.join(outdir,name+'.bin'),'wb').write(buf)
    gl['buffers']=[dict(uri=name+'.bin',byteLength=len(buf))]
    json.dump(gl,open(os.path.join(outdir,name+'.gltf'),'w'))
    return dict(tris=len(T),verts=len(P),surfaces=';'.join('%d:%d'%kv for kv in counts.items()))

def placements(P,nodes):
    """Strat (entity script) placements in a .PCS. The 0x10E object is the strat table; at +0x10:
    ptr code, ptr class records, 0, code size, class count, 0, ptr placements, ptr end, u16 placement
    count. Each placement is 0x3C bytes: f32 quaternion x, y, z, w, f32 position[3], 0, f32 yaw
    (4096 = full turn, 2048 = none), 0, ptr class, ptr params, ptr path, ptr area, u32 index.
    A class record starts with ptr strat table, ptr name, ptr code entry points. A path is a linked
    list of 0x40-byte waypoints (ptr prev, ptr next, f32 xyz), an area a 0x20-byte box
    (u32, ptr, f32 min[3], f32 max[3]). nodes maps draw-node offsets to output names; models a class's
    script file refers to are listed as script_models. Coordinates are game (D3D) world space."""
    m=P.m; T=[ps for t,ps in P.O if t==0x10E and ps]
    if not T: return []
    hdr=T[0][0]; code,clsp,_,_,ncls,_,pl,pe,cnt=struct.unpack_from('<9I',m,hdr+0x10); cnt&=0xFFFF
    R=set(x for t,ps in P.O for x in ps[1:])
    if not (hdr<code<=clsp<=pl<pe<=len(m)) or pl+cnt*0x3C>pe: return []
    def cs(o): return cstr(m,o,64) if 0<o<len(m) else ''
    # class records and the models their script code points at (via a model handle: ptr node, ptr collision)
    cls=[o for o in range(clsp,pl,4) if o in R and u32(m,o)==hdr and o+4 in R]
    entry={c:min([u32(m,c+k) for k in (8,12) if c+k in R and code<=u32(m,c+k)<clsp] or [0]) for c in cls}
    starts=sorted(set(v for v in entry.values() if v)); cptr=sorted(o for o in R if code<=o<clsp)
    models={}
    for c in cls:
        s=entry[c]; ms=set()
        if s:
            i=bisect.bisect_right(starts,s); e=starts[i] if i<len(starts) else clsp
            for o in cptr[bisect.bisect_left(cptr,s):bisect.bisect_left(cptr,e)]:
                v=u32(m,o)
                if v in R and u32(m,v) in nodes: ms.add(nodes[u32(m,v)])
        models[c]=sorted(ms)
    out=[]
    for i in range(cnt):
        o=pl+i*0x3C
        q=struct.unpack_from('<4f',m,o); pos=struct.unpack_from('<3f',m,o+16); yaw=struct.unpack_from('<f',m,o+32)[0]
        c,par,path,area,idx=struct.unpack_from('<5I',m,o+40)
        d=dict(index=idx,cls=cs(u32(m,c+4)) if o+40 in R else '',position=[round(x,4) for x in pos],
               quaternion=[round(x,6) for x in q],yaw_deg=round((yaw-2048)*360/4096,2),script_models=models.get(c,[]))
        if o+48 in R:
            pts=[]; w=path; seen=set()
            while w and w not in seen and w+0x14<=len(m):
                seen.add(w); pts.append([round(x,4) for x in struct.unpack_from('<3f',m,w+8)])
                w=u32(m,w+4) if w+4 in R else 0
            d['path']=pts
        if o+52 in R:
            b=struct.unpack_from('<6f',m,area+8); d['area']=dict(min=[round(x,4) for x in b[:3]],max=[round(x,4) for x in b[3:]])
        out.append(d)
    return out

def write_placements(pl,outdir,name):
    """placements/<level>.json, and a glTF of empty nodes (one per placement, named
    '<index> <class>') with waypoint paths as line strips and areas as boxes."""
    os.makedirs(outdir,exist_ok=True)
    json.dump(pl,open(os.path.join(outdir,name+'.json'),'w'),indent=1)
    gl=dict(asset=dict(version='2.0',generator='bionicle-extract'),scene=0,scenes=[dict(nodes=[])],
            nodes=[],meshes=[],accessors=[],bufferViews=[],
            materials=[dict(name='path',pbrMetallicRoughness=dict(baseColorFactor=[1,0.8,0.1,1])),
                       dict(name='area',pbrMetallicRoughness=dict(baseColorFactor=[0.2,0.6,1,1]))])
    buf=bytearray()
    def acc(a,ct,typ,tgt,minmax=False):
        while len(buf)%4: buf.append(0)
        gl['bufferViews'].append(dict(buffer=0,byteOffset=len(buf),byteLength=a.nbytes,target=tgt)); buf.extend(a.tobytes())
        d=dict(bufferView=len(gl['bufferViews'])-1,componentType=ct,count=len(a),type=typ)
        if minmax: d['min']=[float(x) for x in a.min(0)]; d['max']=[float(x) for x in a.max(0)]
        gl['accessors'].append(d); return len(gl['accessors'])-1
    def lines(nm,P,ix,mode,mat):
        P=np.array(P,'<f4'); P[:,2]*=-1
        gl['meshes'].append(dict(name=nm,primitives=[dict(attributes=dict(POSITION=acc(P,5126,'VEC3',34962,True)),
            indices=acc(np.array(ix,'<u2'),5123,'SCALAR',34963),mode=mode,material=mat)]))
        gl['nodes'].append(dict(name=nm,mesh=len(gl['meshes'])-1)); gl['scenes'][0]['nodes'].append(len(gl['nodes'])-1)
    for d in pl:
        x,y,z,w=d['quaternion']; n=(x*x+y*y+z*z+w*w)**0.5 or 1
        nm='%03d %s'%(d['index'],d['cls'])
        gl['nodes'].append(dict(name=nm,translation=[d['position'][0],d['position'][1],-d['position'][2]],
            rotation=[-x/n,-y/n,z/n,w/n],extras=dict(btg={k:v for k,v in d.items() if k not in ('position','quaternion')})))
        gl['scenes'][0]['nodes'].append(len(gl['nodes'])-1)
        if len(d.get('path',[]))>1: lines(nm+' path',d['path'],list(range(len(d['path']))),3,0)
        if 'area' in d:
            a,b=d['area']['min'],d['area']['max']
            P=[[(a,b)[i&1][0],(a,b)[i>>1&1][1],(a,b)[i>>2&1][2]] for i in range(8)]
            lines(nm+' area',P,[0,1,2,3,4,5,6,7,0,2,1,3,4,6,5,7,0,4,1,5,2,6,3,7],1,1)
    if buf:
        open(os.path.join(outdir,name+'.bin'),'wb').write(buf); gl['buffers']=[dict(uri=name+'.bin',byteLength=len(buf))]
    else:
        for k in ('meshes','accessors','bufferViews'): gl.pop(k)
    json.dump(gl,open(os.path.join(outdir,name+'.gltf'),'w'))

def volt_parse(path):
    d=open(path,'rb').read(1<<20)
    assert d[:4]==b'VOLT', path
    n=struct.unpack_from('<I',d,8)[0]
    ents=[struct.unpack_from('<III',d,16+12*i) for i in range(n)]
    base=16+12*n; out=[]
    for h,one,off in ents:
        p=base+off
        a,b,c,e=struct.unpack_from('<IIII',d,p)
        out.append((d[p+16:d.index(b'\0',p+16)].decode('latin1'),a,c))
    return out

def strip_key(raw,ix):
    """Order-free hash of the triangles a strip draws: the same vertices (all attributes, byte for
    byte) joined into the same triangles with the same winding, however the strip was laid out."""
    ix=np.asarray(ix,dtype=np.int64)
    if len(ix)<3: return hashlib.md5(b'').hexdigest()
    rows=np.ascontiguousarray(raw[ix]).view(np.dtype((np.void,raw.shape[1]))).ravel()
    uniq,inv=np.unique(rows,return_inverse=True); inv=inv.ravel()
    a,b,c=inv[:-2],inv[1:-1],inv[2:]; odd=np.arange(len(a))%2==1
    t=np.stack([np.where(odd,b,a),np.where(odd,a,b),c],1)
    t=t[(t[:,0]!=t[:,1])&(t[:,1]!=t[:,2])&(t[:,0]!=t[:,2])]
    k=t.argmin(1); t=np.stack([t[np.arange(len(t)),(k+i)%3] for i in range(3)],1)
    t=np.unique(t,axis=0) if len(t) else t
    return hashlib.md5(uniq.tobytes()+t.astype('<i4').tobytes()).hexdigest()

def tex_hash(P,texobj,cache):
    """Content hash of a texture, and of every layer and its scroll/rotate settings for an
    animated one (type 0x07), so equal pixels match across packs."""
    if texobj not in cache:
        m=P.m; h=hashlib.md5(); objs=[texobj]
        if P.start.get(texobj)==7:
            n,lp=struct.unpack_from('<2I',m,texobj+0xc)
            if 0<n<9 and lp+0x40*n<=len(m):
                objs=[u32(m,lp+0x40*k) for k in range(n)]
                for k in range(n): h.update(m[lp+0x40*k+4:lp+0x40*(k+1)])
        for o in objs:
            im=P.tga(o)
            h.update(b'none' if im is None else im.tobytes()+im.mode.encode()+bytes(str(im.size),'ascii'))
        cache[texobj]=h.hexdigest()
    return cache[texobj]

def mesh_key(P,batches,th):
    """Fingerprint of what a mesh looks like: the triangles each strip draws (positions, normals,
    colours, UVs; where the mesh sits in its vertex buffer and how the strip is ordered don't matter),
    its textures' pixels, material colour and render/texture-stage/sampler states. Batches are
    hashed one by one and sorted, so the same parts stored in another order still match, and the
    node name is left out, so the same mesh under another name in another level is one file."""
    m=P.m; keys=[]
    for bt in batches:
        h=hashlib.md5(); stride,raw,idx=P.vb(bt['vb']); ix=idx[bt['start']:bt['start']+bt['pc']+2]
        h.update(struct.pack('<2I',stride,bt['fvf'])); h.update(strip_key(raw,ix).encode())
        h.update(tex_hash(P,bt['tex'],th).encode()); h.update(m[bt['off']+0x14:bt['off']+0x18])
        for o,size in ((0x1c,8),(0x24,12),(0x2c,12)):
            c,p=struct.unpack_from('<2I',m,bt['off']+o)
            if 0<c<64: h.update(m[p:p+size*c])
            h.update(b'|')
        keys.append(h.hexdigest())
    return hashlib.md5(''.join(sorted(keys)).encode()).hexdigest()

def mesh_verts(P,batches):
    """Unique vertex positions used by a mesh's triangles."""
    out=[]
    for bt in batches:
        st_,raw,idx=P.vb(bt['vb']); ix=idx[bt['start']:bt['start']+bt['pc']+2]
        if len(ix)<3 or ix.max()>=len(raw): continue
        out.append(raw[np.unique(ix),:12].copy().view('<f4').reshape(-1,3))
    return np.unique(np.concatenate(out),axis=0) if out else np.zeros((0,3),np.float32)

def near_frac(A,B,tol):
    """Fraction of points in A that lie within tol of some point in B."""
    if not len(A) or not len(B): return 0.0
    cells=set(map(tuple,np.floor(B/tol).astype(np.int64)))
    g=np.floor(A/tol).astype(np.int64); hit=0
    for c in map(tuple,g):
        hit+=any((c[0]+x,c[1]+y,c[2]+z) in cells for x in(-1,0,1) for y in(-1,0,1) for z in(-1,0,1))
    return hit/len(A)

def tex_colour(P,texobjs,cache):
    """Mean RGB (0..1) of a model's textures, weighted by pixel count."""
    tot=np.zeros(3); n=0
    for t in set(texobjs):
        if t not in cache:
            im=P.tga(t) if t!=0xffffffff else None
            cache[t]=None if im is None else (np.asarray(im.convert('RGB'),np.float64).reshape(-1,3).sum(0)/255.0,im.size[0]*im.size[1])
        if cache[t] is not None: tot+=cache[t][0]; n+=cache[t][1]
    return tot/n if n else None

def colour_dist(a,b,tol=0.13,ltol=0.15):
    """Colour difference scaled so that under 1 means the same colour scheme: chromaticity (r,g,b over
    their sum) within `tol` and brightness within `ltol`."""
    if a is None or b is None: return 0.0 if a is None and b is None else 9.0
    ca=a/max(a.sum(),1e-6); cb=b/max(b.sum(),1e-6)
    return max(np.linalg.norm(ca-cb)/tol,abs(a.mean()-b.mean())/ltol)

def colour_groups(keys,col):
    """Splits keys into sets whose colours are all close to each other: complete-linkage clustering,
    so a run of in-between colours can't chain green to yellow to white. Only groups of 2 or more."""
    out=[[k] for k in keys]
    while True:
        best=None
        for i in range(len(out)):
            for j in range(i+1,len(out)):
                d=max(colour_dist(col[a],col[c]) for a in out[i] for c in out[j])
                if d<1 and (best is None or d<best[0]): best=(d,i,j)
        if best is None: break
        _,i,j=best; out[i]+=out.pop(j)
    return sorted((sorted(g) for g in out if len(g)>1),key=len,reverse=True)

def union_groups(keys,same,limit=None):
    """Connected components of `same` over `keys` (single linkage); only groups of 2 or more.
    With `limit(a,c)`, keys must be sorted so that once it is true for c it is for every later c."""
    parent={k:k for k in keys}
    def root(k):
        while parent[k]!=k: parent[k]=parent[parent[k]]; k=parent[k]
        return k
    for i,a in enumerate(keys):
        for c in keys[i+1:]:
            if limit and limit(a,c): break
            if root(a)!=root(c) and same(a,c): parent[root(c)]=root(a)
    groups=collections.defaultdict(list)
    for k in keys: groups[root(k)].append(k)
    return sorted((sorted(g) for g in groups.values() if len(g)>1),key=len,reverse=True)

def near_groups(info,share=0.8):
    """Groups entity files that are versions of one mesh. A body group has the same shape: >= `share`
    of each one's vertices lie within 1% of the model size of the other's (only meshes whose vertex
    counts and sizes are within 20% are compared). Different models on one body (the Turaga, the
    Matoran tribes) are then told apart by the mean colour of their textures. `info` maps output ->
    (vertex positions, mean colour); returns [(body, [groups])], largest body first."""
    keys=sorted((k for k in info if len(info[k][0])),key=lambda k:len(info[k][0]))
    ext={k:float(np.ptp(info[k][0],axis=0).max()) for k in keys}
    def body(a,c):
        if min(ext[a],ext[c])<0.8*max(ext[a],ext[c]): return False
        tol=max(0.01*max(ext[a],ext[c]),1e-4)
        return near_frac(info[a][0],info[c][0],tol)>=share and near_frac(info[c][0],info[a][0],tol)>=share
    bodies=union_groups(keys,body,lambda a,c:len(info[c][0])>1.2*len(info[a][0]))
    return [(g,colour_groups(g,{k:info[k][1] for k in g})) for g in bodies]

def write_usage(OUT,rows,verts=None):
    """entities.csv: one row per unique entity file with every level, source and name using it.
    The same lists go into each file as asset.extras.btg {names, levels, sources}, plus {group,
    variants, body} for files that are near-duplicates of others (see near_groups)."""
    use=collections.OrderedDict()
    for r in rows:
        if r.get('kind') not in ('entity','entity(dup)') or not r.get('output'): continue
        u=use.setdefault(r['output'],dict(names=[],levels=[],sources=[],uses=0))
        u['uses']+=1
        lvl=r['source'].split('.')[0]
        for k,v in (('names',r.get('name','')),('levels',lvl),('sources',r['source'])):
            if v not in u[k]: u[k].append(v)
    def gid(g,kind,i):
        nm=collections.Counter(use[o]['names'][0] for o in g).most_common(1)[0][0]
        return '%s__%s%03d'%(re.sub(r'[^A-Za-z0-9._-]+','_',nm).strip('_') or 'unnamed',kind,i)
    group={}; body={}; gi=0
    for bi,(bd,gs) in enumerate(near_groups({o:verts[o] for o in use if o in verts} if verts else {})):
        for o in bd: body[o]=(gid(bd,'b',bi+1),bd)
        for g in gs:
            gi+=1
            for o in g: group[o]=(gid(g,'g',gi),g)
    with open(os.path.join(OUT,'entities.csv'),'w',newline='') as fh:
        w=csv.writer(fh); w.writerow(['output','name','other_names','uses','levels','sources','group','group_size','body','body_size'])
        for o,u in use.items():
            g,gs=group.get(o,('',[])); b,bs=body.get(o,('',[]))
            w.writerow([o,u['names'][0],';'.join(u['names'][1:]),u['uses'],';'.join(u['levels']),';'.join(u['sources']),g,len(gs) or '',b,len(bs) or ''])
    for o,u in use.items():
        fn=os.path.join(OUT,o)
        if not os.path.exists(fn): continue
        with open(fn) as fh: gl=json.load(fh)
        gl['asset'].setdefault('extras',{})['btg']=dict(names=u['names'],levels=u['levels'],sources=u['sources'])
        if o in body: gl['asset']['extras']['btg']['body']=body[o][0]
        if o in group:
            g,gs=group[o]; gl['asset']['extras']['btg'].update(group=g,variants=[x for x in gs if x!=o])
        with open(fn,'w') as fh: json.dump(gl,fh)

TITLES={}
def packs(data_dir):
    for vf in sorted(glob.glob(os.path.join(data_dir,'*.vol'))):
        with open(vf,'rb') as fh:
            for name,off,size in sorted(volt_parse(vf)):
                if not re.search(r'\.PC(M|S|SI)$',name,re.I): continue
                fh.seek(off); d=fh.read(size)
                if d[:4]!=b'BIGB': continue
                r=bigb(d)
                TITLES[name.upper()]=d[0x10:0x50].split(b'\0')[0].decode('latin1').strip()
                yield name.upper(), r['main'], r['rel']

def main():
    global DATA
    if len(sys.argv)!=3: print(__doc__); sys.exit(1)
    DATA,OUT=sys.argv[1],sys.argv[2]
    lv=os.path.join(OUT,'levels'); lib=os.path.join(OUT,'entities'); col=os.path.join(OUT,'collision')
    os.makedirs(lv,exist_ok=True); os.makedirs(lib,exist_ok=True)
    rows=[]; seen={}; libtex={}; verts={}; placed=set(); prow=[]
    def safe(s): return re.sub(r'[^A-Za-z0-9._-]+','_',s).strip('_') or 'unnamed'
    for base,main,rel in packs(DATA):
        stem,ext=base.split('.')
        P=Pack(main,rel)
        g=node_groups(P)
        if not g: rows.append(dict(source=base,kind='empty')); continue
        if ext=='PCM':
            st=write_gltf(P,[(nm,b) for (n,nm),b in g.items()],lv,stem)
            rows.append(dict(source=base,kind='level',output='levels/%s.gltf'%stem,**(st or {})))
            st=write_collision(main,col,stem)
            if st: rows.append(dict(source=base,kind='collision',output='collision/%s.gltf'%stem,**st))
        else:
            tc={}; th={}; th_col={}; nodeout={}
            for (n,nm),b in g.items():
                key=mesh_key(P,b,th)
                if key in seen:
                    nodeout[n]=seen[key]
                    rows.append(dict(source=base,kind='entity(dup)',name=nm,output=seen[key])); continue
                fn='%s__%s'%(safe(nm),key[:6])
                st=write_gltf(P,[(nm,b)],lib,fn,tc)
                if st is None: continue
                seen[key]='entities/%s.gltf'%fn; verts[seen[key]]=(mesh_verts(P,b),tex_colour(P,[bt['tex'] for bt in b],th_col))
                rows.append(dict(source=base,kind='entity',name=nm,output=seen[key],**st)); nodeout[n]=seen[key]
            if stem not in placed:
                pl=placements(P,nodeout)
                if pl:
                    placed.add(stem); write_placements(pl,os.path.join(OUT,'placements'),stem)
                    rows.append(dict(source=base,kind='placements',output='placements/%s.gltf'%stem,nodes=len(pl)))
                    for d in pl: prow.append(dict(source=base,level=stem,index=d['index'],strat=d['cls'],
                        x=d['position'][0],y=d['position'][1],z=d['position'][2],yaw_deg=d['yaw_deg'],
                        path_points=len(d.get('path',[])),area='area' in d,script_models=';'.join(d['script_models'])))
        print(base,flush=True)
    for r in rows: r['title']=TITLES.get(r['source'],'')
    keys=['source','title','kind','name','output','nodes','batches','verts','tris','textures','surfaces']
    with open(os.path.join(OUT,'index.csv'),'w',newline='') as fh:
        w=csv.DictWriter(fh,fieldnames=keys,extrasaction='ignore'); w.writeheader(); [w.writerow(r) for r in rows]
    write_usage(OUT,rows,verts)
    if prow:
        for r in prow: r['title']=TITLES.get(r['level']+'.PCM','')
        with open(os.path.join(OUT,'placements.csv'),'w',newline='') as fh:
            w=csv.DictWriter(fh,fieldnames=list(prow[0])); w.writeheader(); w.writerows(prow)
    print('DONE')

if __name__=='__main__':
    main()
