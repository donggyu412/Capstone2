"""Shared constructive material renderer for two different growth engines.

Only source-region contours/statistics reach this renderer, never image plates.
Background is spatial deposition; object surfaces are bent by evolving graphs.
"""
from dataclasses import dataclass
import json,math
from pathlib import Path
import cv2
import numpy as np
from PIL import Image
from .config import REPO_ROOT
from .emergence_renderer import extract_patches
from .developmental_world import ease


@dataclass
class Group:
    kind: str
    patches: list
    quad: np.ndarray
    support: np.ndarray
    family: str


@dataclass
class Template:
    groups: list
    source: Path


def build_templates(bundle,plans,seed,layout_path=None):
    layout_path=layout_path or Path(__file__).with_name('assumed_layout.json')
    layout=json.loads(layout_path.read_text(encoding='utf-8'))
    templates=[];sources=[layout_path]
    family={'journal':'paper','record':'paper','paper':'paper','figure':'body','hand':'body','pool':'liquid','droplet':'liquid','floor':'floor'}
    for sid,scene in enumerate(bundle.scenes):
        l=layout['scenes'][sid];source=REPO_ROOT/f'team3/background/input/storyboard/scene_{sid+1:02}.png'
        spatial=extract_patches(Image.open(source),'space',l['space'],340,seed+sid)
        groups=[Group('space',spatial,np.array(l['space']),np.zeros(len(spatial)),'space')]
        sources.append(source)
        byrole={rule.role:obj for obj,rule in zip(scene.objects,plans[sid].objects)}
        positions=dict(l['objects'])
        if sid==1:
            # Scene 2 explicitly reuses the pool from scene 1. This is inherited
            # geometry, not an invented extra upstream asset.
            byrole['pool']=bundle.scenes[0].objects[1]
            positions={'pool':layout['scenes'][0]['objects']['pool'],**positions}
        for role,quad in positions.items():
            obj=byrole[role];im=Image.open(obj.path).convert('RGBA')
            im=im.crop(im.getchannel('A').getbbox())
            patches=extract_patches(im,role,quad,75 if role in ('journal','record','hand') else 55,seed+sid*100+obj.index)
            support=np.array([min(spatial,key=lambda b:np.linalg.norm(b.center-p.center)).distance for p in patches])
            groups.append(Group(role,patches,np.array(quad,float),support,family[role]))
            sources.append(obj.path)
        templates.append(Template(groups,source))
    return templates,list(dict.fromkeys(sources)),layout


class DreamSurfaces:
    def __init__(self,templates,width,height,score,seed=101):
        self.templates=templates;self.w=width;self.h=height;self.score=score;self.stats={}
        self.size=np.array([width,height]);self.base=np.array([.025,.034,.043],np.float32)
        self.noise=cv2.resize(np.random.default_rng(seed).random((40,70)).astype('float32'),(width,height),interpolation=cv2.INTER_CUBIC)
        self.cache={};self.cache_hits=0;self.cache_misses=0

    @staticmethod
    def regional_survival(p,sid,t):
        # Primitive growth traces and their developed surfaces share one
        # lifetime, so neither survives an outgoing scene or the final fade.
        start=(sid+1)*75-2+7*p.distance if sid<3 else 281+7*p.distance
        duration=15 if sid<3 else 12
        return 1-float(ease((t-start)/duration))

    def points(self,p,group,index,sid,state,world):
        if p.kind=='space':
            background=state['space']
            progress=(background.formed_extent[index] if hasattr(background,'formed_extent') else background.material[index])
        else:progress=state['objects'][p.kind][index]
        progress*=self.score.material_factor(p.kind,sid,world,p.index)
        # Regional recession: areas persist while the next space grows using
        # inherited trace; this is not a full-frame crossfade.
        death=self.regional_survival(p,sid,world.time)
        if progress<=.003 or death<=.003:return None,0
        expansion=float(ease(progress))*death
        root=p.root if p.kind=='space' else state['roots'][p.kind][index]
        center=root+(p.center-root)*expansion
        points=center+(p.contour-p.center)*expansion
        if p.kind=='space':
            a=state['space'].a[index];b=state['space'].b[index]
            wave=.0018*np.sin(state['age']*.16+p.distance*5)*(a-b)
            points[:,0]+=wave*np.sin(points[:,1]*9)
            points[:,1]+=wave*.4*np.sin(points[:,0]*11)
            overlap=1.09
            if hasattr(state['space'],'mass'):
                mass=state['space'].mass[:,index];mix=mass/max(mass.sum(),1e-8)
                # Competing physical scales visibly bend space at distinct
                # wavelengths. No layer of spots is overlaid on a source plate.
                amplitude=(mix-.333)*.016*expansion
                for scale,frequency in enumerate((27.,12.,4.5)):
                    points[:,0]+=amplitude[scale]*np.sin(points[:,1]*frequency+state['space'].u[scale,index]*3)
                    points[:,1]+=amplitude[scale]*.45*np.sin(points[:,0]*frequency+state['space'].v[scale,index]*4)
                overlap=1.065+.085*mix[2]
        else:
            low=group.quad.min(0);span=np.maximum(group.quad.max(0)-low,.01)
            uv=np.clip((points-low)/span,0,1)
            field=world.controls[p.kind]
            xs=np.clip(uv[:,0]*8,0,7.999);ys=np.clip(uv[:,1]*8,0,7.999)
            ix=xs.astype(int);iy=ys.astype(int);dx=xs-ix;dy=ys-iy
            v=(field[iy,ix]*(1-dx[:,None])*(1-dy[:,None])+field[iy,ix+1]*dx[:,None]*(1-dy[:,None])+
               field[iy+1,ix]*(1-dx[:,None])*dy[:,None]+field[iy+1,ix+1]*dx[:,None]*dy[:,None])
            memory_bias=1 if world.flags['memory_bias'] else 0
            points+=v*span*(.12 if memory_bias else .75)*expansion
            if not memory_bias:
                points=center+(points-center)*[.6,1.3]
            overlap=1.08+.018*math.sin(world.node_counts[p.kind])
        points=center+(points-center)*overlap
        points=self.score.warp(points,p.kind,sid,world)
        return points,expansion

    def add_patch(self,accum,weight,p,points,expansion,origin,color,cachekey):
        screen=points*self.size-origin
        area=abs(cv2.contourArea((p.contour*self.size).astype('float32')))
        radius=max(.65,math.sqrt(area)*(.062+.12*(1-expansion)))
        margin=int(radius*3)+3
        left=max(0,int(screen[:,0].min())-margin);right=min(weight.shape[1],int(screen[:,0].max())+margin+1)
        top=max(0,int(screen[:,1].min())-margin);bottom=min(weight.shape[0],int(screen[:,1].max())+margin+1)
        if right<=left or bottom<=top:return
        # Cache exact subpixel geometry, not arbitrary frame intervals. Fully
        # stable surfaces can be reused without changing motion speed or fps.
        vertices=np.round((screen-[left,top])*4).astype('int32')
        signature=(vertices.tobytes(),right-left,bottom-top,round(radius,2))
        cached=self.cache.get(cachekey)
        if cached is not None and cached[0]==signature:
            alpha=cached[1];self.cache_hits+=1
        else:
            mask=np.zeros((bottom-top,right-left),np.uint8)
            cv2.fillPoly(mask,[vertices],255,cv2.LINE_AA,shift=2)
            alpha=cv2.GaussianBlur(mask.astype('float32')/255,(0,0),radius)
            self.cache[cachekey]=(signature,alpha);self.cache_misses+=1
        accum[top:bottom,left:right]+=alpha[:,:,None]*color
        weight[top:bottom,left:right]+=alpha

    def render(self,world,*,separate=False):
        canvas=np.empty((self.h,self.w,3),np.float32);canvas[:]=self.base
        backgrounds=canvas.copy() if separate else None
        objects=canvas.copy() if separate else None
        stats={};detail=[]
        for sid,state in world.active():
            template=self.templates[sid];stats[sid+1]={}
            for group in template.groups:
                kind=group.kind;prepared=[];coverage=0
                if kind!='space':
                    self.draw_grammar_trace(canvas,group,sid,state,world)
                    if separate:self.draw_grammar_trace(objects,group,sid,state,world)
                for j,p in enumerate(group.patches):
                    points,amount=self.points(p,group,j,sid,state,world)
                    if points is None:continue
                    prepared.append((j,p,points,amount))
                    coverage+=abs(cv2.contourArea((points*self.size).astype('float32')))
                stats[sid+1][kind]={'regions':len(prepared),'area':coverage}
                if not prepared:continue
                allpoints=np.concatenate([x[2] for x in prepared])*self.size
                lo=np.maximum(0,np.floor(allpoints.min(0)-24)).astype(int)
                hi=np.minimum(self.size,np.ceil(allpoints.max(0)+25)).astype(int)
                rw,rh=hi-lo
                if rw<=0 or rh<=0:continue
                # Rasterize the developed regional geometry into one material
                # layer, then diffuse pigment across its boundaries. This is
                # native-resolution geometry at every frame, not upscaling or
                # optical-flow fabrication of intermediate animation frames.
                layer=np.zeros((rh,rw,4),np.uint8)
                for j,p,points,amount in prepared:
                    color=p.color if kind=='space' else state['source_colors'][kind][j]
                    pigment=np.power(np.clip(color*.79+p.light*.21,0,1),.82)*[.88,.99,1.02]
                    if kind=='figure':pigment=pigment*.64+[.025,.037,.042]
                    elif kind in ('journal','record','paper','hand','droplet'):pigment=pigment*.76+[.027,.033,.035]
                    elif kind=='pool':pigment=pigment*.42+[.037,.067,.073]
                    elif kind=='floor':pigment=pigment*.32+[.033,.043,.047]
                    # Low-frequency local illumination binds each object to its
                    # spatial material, not an independent white sprite layer.
                    vertices=np.round((points*self.size-lo)*4).astype('int32')
                    cv2.fillPoly(layer,[vertices],tuple(float(np.clip(v*255,0,255)) for v in (*pigment,1.)),cv2.LINE_AA,shift=2)
                layer=cv2.GaussianBlur(layer,(0,0),max(.8,1.6*self.w/960))
                if kind=='space' and hasattr(state['space'],'mass'):
                    # Do not turn competing space into a regular checkerboard
                    # by shrinking each source cluster about its own centre.
                    # Once connected material exists, competition changes its
                    # continuous density at three spatial scales instead.
                    density=self.background_density(state['space'])
                    density=cv2.resize(density,(self.w,self.h),interpolation=cv2.INTER_CUBIC)
                    density=np.clip(density[lo[1]:hi[1],lo[0]:hi[0]],0,1)
                    layer=(layer.astype('float32')*density[:,:,None]).astype('uint8')
                alpha=layer[:,:,3].astype('float32')/255
                grain=(.94+.10*self.noise[lo[1]:hi[1],lo[0]:hi[0]])/255
                region=canvas[lo[1]:hi[1],lo[0]:hi[0]]
                region*=1-alpha[:,:,None]
                region+=layer[:,:,:3]*grain[:,:,None]
                if separate:
                    target=backgrounds if kind=='space' else objects
                    target_region=target[lo[1]:hi[1],lo[0]:hi[0]]
                    target_region*=1-alpha[:,:,None]
                    target_region+=layer[:,:,:3]*grain[:,:,None]
                detail.append((sid,group,state,world))
            self.draw_story_details(canvas,sid,state,world)
            if separate:
                self.draw_story_details(backgrounds,sid,state,world,only='background')
                self.draw_story_details(objects,sid,state,world,only='objects')
        # Bloom is low-frequency light only; geometry remains full resolution.
        self.stats={'scene_surfaces':stats,'source_pixels_composited':0,
                    'background_engine':'memory RD, evolved generator parameters, 3-scale resource competition',
                    'object_engine':'connected morphology graph mutation/recombination/QD'}
        def finish(c):
            light=np.maximum(cv2.resize(c,(self.w//4,self.h//4),interpolation=cv2.INTER_AREA)-.55,0)
            c=c+cv2.resize(cv2.GaussianBlur(light,(0,0),max(.7,.75*self.w/960)),(self.w,self.h))*.09
            return (np.clip(c,0,1)*255).astype('uint8')
        if separate:return {'background':finish(backgrounds),'objects':finish(objects),'integrated':finish(canvas)}
        return finish(canvas)

    def background_density(self,background):
        width,height=160,90
        xy=np.clip(background.centers*[width-1,height-1],[0,0],[width-1,height-1]).astype(int)
        flat=xy[:,1]*width+xy[:,0]
        count=np.bincount(flat,minlength=width*height).reshape(height,width).astype('float32')
        fields=[]
        for scale,sigma in enumerate((2.,4.,7.)):
            value=np.clip(background.mass[scale]/.28,0,1)
            numerator=np.bincount(flat,weights=value,minlength=width*height).reshape(height,width).astype('float32')
            den=cv2.GaussianBlur(count,(0,0),sigma)
            fields.append(cv2.GaussianBlur(numerator,(0,0),sigma)/np.maximum(den,1e-6))
        density=np.mean(fields,axis=0)
        # Early birth already comes from actual geometry. Keep tiny newborn
        # surfaces visible; later competitive losses thin connected matter.
        return .30+.70*np.clip(density,0,1)

    def draw_grammar_trace(self,canvas,group,sid,state,world):
        values=state['objects'][group.kind]
        order=np.argsort([p.distance for p in group.patches])
        chosen=order[::max(1,len(order)//7)][:7]
        for j in chosen:
            amount=values[j]
            if amount<.01 or amount>.76:continue
            p=group.patches[j];root=state['roots'][group.kind][j]
            survival=self.regional_survival(p,sid,world.time)
            if survival<=.003:continue
            center=root+(p.center-root)*float(ease(amount/.55))
            bend=world.controls[group.kind].mean((0,1))*.02
            points=np.array([root,(root+center)/2+bend,center])
            points=self.score.warp(points,group.kind,sid,world)*self.size
            lo=np.maximum(0,np.floor(points.min(0)-5)).astype(int);hi=np.minimum(self.size,np.ceil(points.max(0)+6)).astype(int)
            if np.any(hi<=lo):continue
            mask=np.zeros((hi[1]-lo[1],hi[0]-lo[0]),np.uint8)
            cv2.polylines(mask,[(points-lo).astype('int32')],False,255,max(1,round(self.w/960)),cv2.LINE_AA)
            opacity=float(ease(amount/.15))*(1-float(ease((amount-.35)/.41)))*.45*survival
            alpha=cv2.GaussianBlur(mask.astype('float32')/255,(0,0),.6)*opacity
            colour=np.minimum(.6,p.color*.55+.10)
            region=canvas[lo[1]:hi[1],lo[0]:hi[0]]
            region+=(colour-region)*alpha[:,:,None]

    def draw_story_details(self,canvas,sid,state,world,only=None):
        if not world.flags['story']:return
        t=world.time;end=(sid+1)*75
        alive=1-float(ease((t-(end-1))/12)) if sid<3 else 1-float(ease((t-286)/12))
        if alive<=0:return
        def stroke(points,color,width=1,amount=1,kind='space'):
            if only=='background' and kind!='space':return
            if only=='objects' and kind=='space':return
            pts=self.score.warp(np.array(points,float),kind,sid,world)
            pts=(pts*self.size).astype('int32')
            # Local ROI avoids copying the entire full-HD frame for tiny ink.
            lo=np.maximum(pts.min(0)-6,0);hi=np.minimum(pts.max(0)+7,self.size)
            if np.any(hi<=lo):return
            mask=np.zeros((hi[1]-lo[1],hi[0]-lo[0]),np.uint8)
            cv2.polylines(mask,[(pts-lo)],False,255,max(1,round(width*self.w/960)),cv2.LINE_AA)
            a=cv2.GaussianBlur(mask.astype('float32')/255,(0,0),max(.55,self.w/1920))
            a*=max(0,min(1,amount))*alive
            r=canvas[lo[1]:hi[1],lo[0]:hi[0]];r+=(np.array(color,np.float32)-r)*a[:,:,None]
        readiness=lambda role:float(np.mean(state['objects'].get(role,np.zeros(1))))
        if sid==0:
            m=readiness('journal');erase=self.score.p('erase',t)
            for j in range(5):
                stroke([[.345,.804+j*.007],[.375,.805+j*.007],[.396,.802+j*.007]],
                       [.075,.085,.080],amount=m*(1-erase)*.8,kind='journal')
        elif sid==1:
            m=readiness('record');writing=(.5+.5*math.sin((t-96)*.6))*self.score.p('writing',t)
            for j in range(6):
                stroke([[.231,.46+j*.012],[.265,.463+j*.012],[.302,.46+j*.012]],
                       [.075,.092,.080],amount=m*writing*(1-self.score.p('erase_before_water',t)),kind='record')
        elif sid in (2,3):
            m=max(readiness('floor'),readiness('record'))
            q=self.score.p('crack' if sid==2 else 'anticipatory_crack',t)
            if sid==3:q=max(q,.5*float(ease((t-287)/11)))
            for j in range(7):
                x=.30+j*.054;y=.87-.08*(j%2)
                pts=np.array([[.50,.88],[x,y],[x-.022,y-.044],[x+.015,y-.075]])
                # Fissures grow geometrically from the deposited memory centre.
                pts=pts[0]+(pts-pts[0])*q
                stroke(pts,[.022,.03,.033],width=1.3,amount=m*q*.85)
            if sid==3:
                m=readiness('record');q=self.score.p('pages',t)
                count=32+(27-32)*float(ease(q*2))+(40-27)*float(ease((q-.5)*2))
                for j in range(40):
                    visibility=float(np.clip(count-j,0,1))*m*.45
                    stroke([[.267,.733+j*.0016],[.425,.736+j*.0016]],
                           [.12,.135,.12],amount=visibility,kind='record')
