#!/usr/bin/env python3
"""BIONICLE: The Game (2003, PC) model extractor.

Usage: python btg_models.py <path-to-game>/Data <output-folder>
Needs: Python 3.8+, numpy, Pillow  (pip install numpy pillow)

Reads the .vol archives read-only, decompresses the BIGB level/entity files
(.PCM = level, .PCS/.PCSI = entities), and writes glTF 2.0 (.gltf + .bin + PNG textures):
  <out>/levels/<level>.gltf      whole level geometry, world space
  <out>/entities/<name>__<hash>.gltf   each entity mesh in bind pose, deduplicated
  <out>/index.csv                which source file produced what
Format notes are in FORMAT_NOTES.md next to this script.
"""
import sys,os,glob,json,hashlib,re,collections,csv,struct,io
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
    material colour (ARGB); its alpha is the batch opacity."""
    cnt,p=struct.unpack_from('<2I',m,b+0x1c)
    rs={}
    if 0<cnt<64 and p+8*cnt<=len(m):
        v=struct.unpack_from('<%dI'%(2*cnt),m,p); rs=dict(zip(v[0::2],v[1::2]))
    src,dst=rs.get(19,5),rs.get(20,6)
    if rs.get(15)==1: mode='cutout'
    elif rs.get(27)==1 or (rs.get(27)!=0 and (19 in rs or 20 in rs)):
        mode=BLEND_NAMES.get((src,dst),'alpha' if dst!=2 else 'additive')
    else: mode='opaque'
    alpha=(u32(m,b+0x14)>>24)/255.0 if mode in('alpha','additive') else 1.0
    return (mode,rs.get(14,1)!=0,src,dst,round(alpha,4))

TEXOPS={1:'disable',2:'selectArg1',3:'selectArg2',4:'modulate',5:'modulate2x',6:'modulate4x',7:'add',
        8:'addSigned',9:'addSigned2x',10:'subtract',11:'addSmooth',12:'blendDiffuseAlpha',13:'blendTextureAlpha'}
def tex_layers(m,texobj,b):
    """Animated texture (relocation type 0x07): +0x0C layer count, +0x10 ptr to 0x40-byte layers:
    ptr texture, f32 scrollU, scrollV (UV units/s), rotate (rad/s), f32[4] tint, f32[3] unknown (wave?).
    Layer k>0 is combined onto the result by the colour op of texture stage k (batch +0x24 list)."""
    n,lp=struct.unpack_from('<2I',m,texobj+0xc)
    if not 0<n<9 or lp+0x40*n>len(m): return None
    c,p=struct.unpack_from('<2I',m,b+0x24); ops={}
    if 0<c<64 and p+12*c<=len(m):
        t=struct.unpack_from('<%dI'%(3*c),m,p)
        ops={t[i]:t[i+2] for i in range(0,3*c,3) if t[i+1]==1}
    out=[]
    for k in range(n):
        w=struct.unpack_from('<I15f',m,lp+0x40*k)
        out.append(dict(tex=w[0],op='base' if k==0 else TEXOPS.get(ops.get(k),'modulate'),
            scroll=[round(w[1],5),round(w[2],5)],rotate=round(w[3],5),tint=[round(x,4) for x in w[4:8]],
            params=[round(x,5) for x in w[8:11]]))
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
            if t not in (0x20,0x21,0x22): continue
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
    def material(tex,bs=None,valpha=False,boff=None):
        if bs is not None and bs[0]=='alpha' and bs[4]>=1 and not valpha:
            im_mode=texcache[tex][1] if tex in texcache else None
            if tex not in texcache:
                im=P.tga(tex) if tex!=0xffffffff else None
                im_mode='RGBA' if im is not None and im.mode in('RGBA','LA','PA','P') and 'A' in im.getbands() and im.getextrema()[-1][0]<255 else 'RGB'
            if im_mode!='RGBA': bs=None   # blend state set, but nothing is see-through: keep it opaque
        layers=tex_layers(P.m,tex,boff) if boff is not None and P.start.get(tex)==7 else None
        key=(tex,bs if bs and bs[0]!='opaque' else None,tuple(l['op'] for l in layers) if layers else None)
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
                if alpha<1: mat['pbrMetallicRoughness']['baseColorFactor']=[1.0,1.0,1.0,alpha]
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
            prims.append(dict(attributes=attrs,indices=ia,material=material(bt['tex'],bt.get('bs'),bool(stride==24 and (v[:,15]<255).any()),bt['off'])))
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
    lv=os.path.join(OUT,'levels'); lib=os.path.join(OUT,'entities')
    os.makedirs(lv,exist_ok=True); os.makedirs(lib,exist_ok=True)
    rows=[]; seen={}; libtex={}
    def safe(s): return re.sub(r'[^A-Za-z0-9._-]+','_',s).strip('_') or 'unnamed'
    for base,main,rel in packs(DATA):
        stem,ext=base.split('.')
        P=Pack(main,rel)
        g=node_groups(P)
        if not g: rows.append(dict(source=base,kind='empty')); continue
        if ext=='PCM':
            st=write_gltf(P,[(nm,b) for (n,nm),b in g.items()],lv,stem)
            rows.append(dict(source=base,kind='level',output='levels/%s.gltf'%stem,**(st or {})))
        else:
            tc={}
            for (n,nm),b in g.items():
                # geometry fingerprint for dedupe across packs
                h=hashlib.md5()
                for bt in b:
                    stride,raw,idx=P.vb(bt['vb']); h.update(idx[bt['start']:bt['start']+bt['pc']+2].tobytes()); h.update(raw[idx[bt['start']:bt['start']+bt['pc']+2]].tobytes())
                key=(nm,h.hexdigest())
                if key in seen:
                    rows.append(dict(source=base,kind='entity(dup)',name=nm,output=seen[key])); continue
                fn='%s__%s'%(safe(nm),h.hexdigest()[:6])
                st=write_gltf(P,[(nm,b)],lib,fn,tc)
                if st is None: continue
                seen[key]='entities/%s.gltf'%fn
                rows.append(dict(source=base,kind='entity',name=nm,output=seen[key],**st))
        print(base,flush=True)
    for r in rows: r['title']=TITLES.get(r['source'],'')
    keys=['source','title','kind','name','output','nodes','batches','verts','tris','textures']
    with open(os.path.join(OUT,'index.csv'),'w',newline='') as fh:
        w=csv.DictWriter(fh,fieldnames=keys,extrasaction='ignore'); w.writeheader(); [w.writerow(r) for r in rows]
    print('DONE')

if __name__=='__main__':
    main()
