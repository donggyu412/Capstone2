"""Source-region contours, adjacency and colour statistics."""
from dataclasses import dataclass
import heapq
import cv2
import numpy as np

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
