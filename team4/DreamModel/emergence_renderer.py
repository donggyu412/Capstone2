"""Constructive patches grow from source-derived geometry on an empty field.

Only contours, adjacency and regional colour statistics reach the renderer.
No complete source image or RGBA sprite is composited into a video frame.
"""
from dataclasses import dataclass
import heapq
import cv2
import numpy as np
from PIL import Image
from .developmental_world import ease


def segment_regions(rgb,mask,count,compactness):
    """Local colour/spatial clustering; no extra compiled package dependency."""
    h,w=mask.shape;step=max(3,int(np.sqrt(mask.sum()/count)))
    lab=cv2.cvtColor(rgb.astype('float32'),cv2.COLOR_RGB2LAB)
    yy,xx=np.mgrid[:h,:w].astype('float32')
    seeds=[]
    for y in range(step//2,h,step):
        for x in range(step//2,w,step):
            if mask[y,x]:seeds.append([float(x),float(y),*lab[y,x]])
    if not seeds:return mask.astype('int32')
    centers=np.array(seeds,float)
    labels=np.zeros((h,w),np.int32)
    for iteration in range(5):
        distances=np.full((h,w),np.inf,np.float32)
        for i,(x,y,l,a,b) in enumerate(centers,start=1):
            x0=max(0,int(x-2*step));x1=min(w,int(x+2*step+1))
            y0=max(0,int(y-2*step));y1=min(h,int(y+2*step+1))
            local=lab[y0:y1,x0:x1]
            d=np.sum((local-[l,a,b])**2,axis=2)
            d+=((xx[y0:y1,x0:x1]-x)**2+(yy[y0:y1,x0:x1]-y)**2)*(compactness/step)**2
            choose=(d<distances[y0:y1,x0:x1])&mask[y0:y1,x0:x1]
            distances[y0:y1,x0:x1][choose]=d[choose]
            labels[y0:y1,x0:x1][choose]=i
        for i in range(1,len(centers)+1):
            region=labels==i
            if region.any():centers[i-1]=[xx[region].mean(),yy[region].mean(),*lab[region].mean(axis=0)]
    return labels


@dataclass
class Patch:
    kind: str
    index: int
    contour: np.ndarray
    center: np.ndarray
    color: np.ndarray
    light: np.ndarray
    neighbors: tuple
    distance: float
    parent: int
    root: np.ndarray
    area: float


def extract_patches(image,kind,quad,segments,seed):
    rgba=np.asarray(image.convert('RGBA').resize((320,180) if kind=='space' else (180,200)),np.float32)/255
    rgb=rgba[:,:,:3]
    mask=rgba[:,:,3]>.2
    labels=segment_regions(rgb,mask,segments,6.5 if kind=='space' else 3.0)
    n=int(labels.max());contours={};centers={};colors={};lights={};areas={}
    adj={i:set() for i in range(1,n+1)}
    h,w=labels.shape
    for a,b in ((labels[:,:-1],labels[:,1:]),(labels[:-1],labels[1:])):
        edges=np.unique(np.column_stack((a.ravel(),b.ravel())),axis=0)
        for x,y in edges:
            if x and y and x!=y:adj[x].add(int(y));adj[y].add(int(x))
    quad=np.asarray(quad,float)
    def project(points):
        u=points[:,0,None];v=points[:,1,None]
        return (1-u)*(1-v)*quad[0]+u*(1-v)*quad[1]+u*v*quad[2]+(1-u)*v*quad[3]
    for i in range(1,n+1):
        region=(labels==i).astype('uint8')
        c,_=cv2.findContours(region,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        if not c:continue
        c=max(c,key=cv2.contourArea)
        perimeter=cv2.arcLength(c,True)
        c=cv2.approxPolyDP(c,max(.5,perimeter*.008),True)[:,0].astype(float)
        if len(c)<3:continue
        ys,xs=np.where(region)
        contours[i]=project(c/[w,h]);centers[i]=project(np.array([[xs.mean()/w,ys.mean()/h]]))[0]
        pixels=rgb[region>0]
        colors[i]=np.quantile(pixels,.50,axis=0);lights[i]=np.quantile(pixels,.85,axis=0)
        areas[i]=len(xs)/(h*w)
    if not centers:return []
    # Parent graph follows spatial adjacency, so patches originate from an
    # already growing neighbour rather than randomly popping across the canvas.
    origin=np.array([.53,.59]) if kind=='space' else quad.mean(axis=0)
    root=min(centers,key=lambda i:np.linalg.norm((centers[i]-origin)*[1,.6]))
    distance={root:0.};parent={root:root};queue=[(0.,root)]
    while queue:
        d,i=heapq.heappop(queue)
        if d!=distance[i]:continue
        for j in adj[i]:
            if j not in centers:continue
            candidate=d+np.linalg.norm((centers[j]-centers[i])*[1,.75])+.003
            if candidate<distance.get(j,1e9):
                distance[j]=candidate;parent[j]=i;heapq.heappush(queue,(candidate,j))
    maxdist=max(distance.values()) or 1
    patches=[]
    for i in centers:
        ancestor=parent.get(i,root)
        start=centers[ancestor]*.55+centers[i]*.45
        patches.append(Patch(kind,i,contours[i],centers[i],colors[i],lights[i],tuple(adj[i]),
            min(1,distance.get(i,maxdist)/maxdist),ancestor,start,areas[i]))
    return patches


class EmergenceRenderer:
    def __init__(self,bundle,plans,width,height,seed=101):
        self.w,self.h=width,height;self.seed=seed;self.stats={}
        self.yy,self.xx=np.mgrid[:height,:width].astype('float32')
        self.rng=np.random.default_rng(seed)
        self.patches=[]
        from .config import REPO_ROOT
        spatial=REPO_ROOT/'team3/background/input/storyboard/scene_01.png'
        self.patches+=extract_patches(Image.open(spatial),'space',[[0,0],[1,0],[1,1],[0,1]],340,seed)
        placement={'journal':[[.19,.77],[.46,.75],[.49,.90],[.16,.91]],
                   'pool':[[.47,.812],[.69,.812],[.72,.872],[.45,.875]],
                   'figure':[[.55,.23],[.78,.23],[.76,.74],[.54,.74]]}
        for obj,rule in zip(bundle.scenes[0].objects,plans[0].objects):
            image=Image.open(obj.path).convert('RGBA');image=image.crop(image.getchannel('A').getbbox())
            self.patches+=extract_patches(image,rule.role,placement[rule.role],
                75 if rule.role=='journal' else 55,seed+obj.index)
        self.patches.sort(key=lambda p:({'space':0,'figure':1,'pool':2,'journal':3}.get(p.kind,4),p.distance))
        spatial_patches=[p for p in self.patches if p.kind=='space']
        self.support={id(p):min(spatial_patches,key=lambda b:np.linalg.norm(b.center-p.center)).distance
                      for p in self.patches if p.kind!='space'}
        self.initial=np.empty((height,width,3),np.float32);self.initial[:]=[.025,.034,.043]
        self.canvas=self.initial.copy()
        self.noise=cv2.resize(self.rng.random((40,70)).astype('float32'),(width,height),interpolation=cv2.INTER_CUBIC)
        self.births={p.kind:0. for p in self.patches}
        self.rendered_areas={}
        self.color_sum=np.zeros((height,width,3),np.float32)
        self.weight=np.zeros((height,width),np.float32)

    def patch(self,p,world,progress):
        # The evolved genotype changes both the growth trajectory and the
        # developed contour. There is no target-image alpha reveal here.
        if progress<=0:return 0.
        g=world.genes[p.kind];nodes=world.node_amount[p.kind]
        expansion=float(ease(progress))
        center=p.root+(p.center-p.root)*expansion
        points=center+(p.contour-p.center)*expansion
        angle=(g[0]-.5)*.30*(1-expansion)
        c,s=np.cos(angle),np.sin(angle)
        points=center+(points-center)@np.array([[c,-s],[s,c]])
        variation=(g[1]-.5)*.025
        points[:,0]+=np.sin(points[:,1]*13+g[2]*3)*variation*expansion
        points[:,1]+=np.sin(points[:,0]*17+g[3]*3)*variation*.5*expansion
        # Slight overlap joins neighbouring material surfaces without visible
        # segmentation cells. Extra folds come from selected structural nodes.
        points=center+(points-center)*(1.08+.018*np.sin(nodes))
        screen=points*[self.w,self.h]
        projected_area=abs(cv2.contourArea((p.contour*[self.w,self.h]).astype('float32')))
        radius=max(.65,np.sqrt(projected_area)*(.065+.14*(1-expansion)))
        margin=int(radius*4)+3
        left=max(0,int(screen[:,0].min())-margin);right=min(self.w,int(screen[:,0].max())+margin+1)
        top=max(0,int(screen[:,1].min())-margin);bottom=min(self.h,int(screen[:,1].max())+margin+1)
        if right<=left or bottom<=top:return 0.
        mask=np.zeros((bottom-top,right-left),np.uint8)
        cv2.fillPoly(mask,[(screen-[left,top]).astype('int32')],255,cv2.LINE_AA)
        alpha=cv2.GaussianBlur(mask.astype('float32')/255,(0,0),radius)
        # All patches, including objects, share one light/material response.
        pigment=p.color*.79+p.light*.21
        pigment=np.power(np.clip(pigment,0,1),.82)*[.88,.99,1.02]
        if p.kind=='figure':pigment=pigment*.72+np.array([.025,.037,.042])
        elif p.kind=='journal':pigment=pigment*.82+np.array([.027,.033,.035])
        elif p.kind=='pool':pigment=pigment*.42+np.array([.037,.067,.073])
        fine=self.noise[top:bottom,left:right]
        color=pigment[None,None,:]*(.94+.10*fine[:,:,None])
        self.color_sum[top:bottom,left:right]+=color*alpha[:,:,None]
        self.weight[top:bottom,left:right]+=alpha
        return float(abs(cv2.contourArea(screen.astype('float32'))))

    def render(self,world):
        self.canvas=self.initial.copy()
        counts={k:0 for k in ('space','journal','pool','figure')}
        areas={k:0. for k in counts};maxp={k:0. for k in counts}
        # Shared condition clock does not accelerate the source audio/video.
        t=world.development_time
        role_rank={o.role:o.reveal_rank for o in world.plans[0].objects}
        active=None
        def settle():
            if active is None:return
            color=self.color_sum/np.maximum(self.weight[:,:,None],.0001)
            coverage=(1-np.exp(-self.weight*3.2)).astype('float32')
            self.canvas+=(color-self.canvas)*coverage[:,:,None]
        for patch in self.patches:
            kind=patch.kind;g=world.genes[kind]
            if kind!=active:
                settle();active=kind;self.color_sum[:]=0;self.weight[:]=0
            if kind=='space':
                birth=.7+patch.distance*(22.+4*g[0])
                duration=7.5+3*g[1]
            else:
                order=role_rank[kind] if world.enabled['story'] else 1.
                birth=2.5+order*3.+patch.distance*(10.+2*g[0])
                birth=max(birth,.7+self.support[id(patch)]*24.-3.)
                duration=8.+4*g[1]
            # Background availability gently delays ungrounded foreground
            # patches instead of depositing finished stickers over empty space.
            if kind!='space':birth+=1.5*max(0,.62-patch.center[1])
            progress=float(np.clip((t-birth)/duration,0,1))
            area=self.patch(patch,world,progress)
            if area>1:counts[kind]+=1;areas[kind]+=area;maxp[kind]=max(maxp[kind],progress)
        settle()
        # Bloom is only emitted by existing material; it cannot reveal an image.
        light=np.maximum(self.canvas-.55,0)
        frame=self.canvas+cv2.GaussianBlur(light,(0,0),3.)*.09
        self.stats={'original_seconds':world.time,'development_time':t,
            'visible_patches':counts,'surface_area_pixels':areas,'maximum_progress':maxp,
            'source_pixels_composited':0,'method':'connected source-derived regional surfaces; finite grammar'}
        return (np.clip(frame,0,1)*255).astype('uint8')
