import struct,sys,os,collections,json
def parse(p):
    f=open(p,'rb'); d=f.read(0x400000)
    mag,ver,n,nb=struct.unpack_from('<4sIII',d,0)
    assert mag==b'VOLT',p
    idx=16
    hashes=[struct.unpack_from('<III',d,idx+12*i) for i in range(n)]
    base=idx+12*n
    out=[]
    for h,one,off in hashes:
        o,a,s,b=struct.unpack_from('<IIII',d,base+off)
        name=d[base+off+16:d.index(b'\0',base+off+16)].decode('latin1')
        out.append((name,o,a,s,b))
    return out,f
D='/mnt/project-files/BIONICLE/Data/'
res={}
for fn in sorted(os.listdir(D)):
    ents,f=parse(D+fn)
    fl=[]
    for name,o,a,s,b in ents:
        f.seek(o); hd=f.read(16)
        fl.append(dict(name=name,off=o,a=a,size=s,b=b,head=hd.hex()))
    res[fn]=fl
json.dump(res,open('index.json','w'),indent=0)
for fn,fl in res.items():
    c=collections.Counter(os.path.splitext(x['name'])[1].upper() for x in fl)
    print(fn,len(fl),dict(c), 'flags a:',set(x['a'] for x in fl),'b:',set(x['b'] for x in fl))
