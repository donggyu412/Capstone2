"""Source-textured developmental surfaces with spatial memory and story events.

Background: hierarchical regional growth and a persistent displacement field.
Objects: connected UV surfaces extend from roots and change curvature/topology.
This bounded 2.5D interpretation uses supplied assets; it is not learned 3D,
unrestricted OEE, or physically calibrated reconstruction.
"""
from __future__ import annotations
import math
import cv2
import numpy as np
from PIL import Image
from .developmental_world import ease


def mix(a,b,t):
    return np.asarray(a)*(1-t)+np.asarray(b)*t


class VisualMemories:
    def __init__(self,bundle,plans,spatial_paths):
        self.scene_palettes=[];self.object_colors={};self.shape_features={}
        self.sources=[];self.assets={};self.backgrounds=[]
        for scene,plan,spatial in zip(bundle.scenes,plans,spatial_paths):
            raw=np.asarray(Image.open(spatial).convert('RGB'),np.float32)/255
            delivered=np.asarray(Image.open(scene.background_path).convert('RGB').resize((96,54)),np.float32)/255
            small=cv2.resize(raw,(96,54))
            rgb=.90*small+.10*delivered
            self.backgrounds.append(raw)
            self.scene_palettes.append({'wall':np.median(rgb[:35],axis=(0,1)),
                'floor':np.median(rgb[35:],axis=(0,1)),'light':np.quantile(rgb.reshape(-1,3),.86,axis=0)})
            self.sources.extend((spatial,scene.background_path))
            for obj,rule in zip(scene.objects,plan.objects):
                image=Image.open(obj.path).convert('RGBA')
                image=image.crop(image.getchannel('A').getbbox())
                image.thumbnail((360,360),Image.Resampling.LANCZOS)
                rgba=np.asarray(image,np.float32)/255
                mask=rgba[:,:,3]>.3;pixels=rgba[:,:,:3][mask]
                self.object_colors[(scene.scene_id,rule.role)]=np.quantile(pixels,(.15,.55,.90),axis=0)
                ys,xs=np.where(mask)
                edge=cv2.Canny((rgba[:,:,:3]*255).astype('uint8'),70,140)>0
                self.shape_features[(scene.scene_id,rule.role)]=[
                    float((xs.max()-xs.min()+1)/(ys.max()-ys.min()+1)),float(mask.mean()),
                    float((edge&mask).sum()/max(mask.sum(),1)),float(np.mean(mask!=mask[:,::-1]))]
                self.assets[(scene.scene_id,rule.role)]=rgba
                self.sources.append(obj.path)
        gray=cv2.cvtColor((cv2.resize(self.backgrounds[0],(96,54))*255).astype('uint8'),cv2.COLOR_RGB2GRAY)
        gx,gy=np.gradient(gray.astype(float))
        self.spatial_bias=np.array([np.mean(abs(gx)),np.mean(abs(gy))])*.009


class DevelopmentalRenderer:
    def __init__(self,width,height,memories,seed=101):
        self.w,self.h=width,height;self.memories=memories
        self.rng=np.random.default_rng(seed+491);self.stats={};self.frame_count=0
        self.yy,self.xx=np.mgrid[:height,:width].astype('float32')
        self.x=self.xx/width;self.y=self.yy/height
        self.backgrounds=[cv2.resize(b,(width,height),interpolation=cv2.INTER_AREA) for b in memories.backgrounds[:2]]
        gray=[cv2.cvtColor((cv2.resize(b,(240,135))*255).astype('uint8'),cv2.COLOR_RGB2GRAY) for b in self.backgrounds]
        self.flow=[]
        for a,b in (gray,gray[::-1]):
            flow=cv2.calcOpticalFlowFarneback(a,b,None,.5,4,35,5,7,1.5,0)
            flow=cv2.GaussianBlur(flow,(0,0),4.)
            flow=cv2.resize(flow,(width,height))*np.array([width/240,height/135],np.float32)
            self.flow.append(np.clip(flow,[-width*.14,-height*.14],[width*.14,height*.14]).astype('float32'))
        self.grain=cv2.resize(self.rng.random((34,60)).astype('float32'),(width,height),interpolation=cv2.INTER_CUBIC)
        self.front=cv2.resize(self.rng.random((5,9)).astype('float32'),(width,height),interpolation=cv2.INTER_CUBIC)
        self.trace=np.zeros((height,width),np.float32)
        self.previous_phase=0.;self.last_time=None
        self.transitions=[];self.mesh_faces=0
        self.figure_tex=self.texture(1,'figure')
        self.book_tex=self.texture(1,'journal')
        self.pool_tex=self.texture(1,'pool')
        self.record_tex=self.texture(2,'record')
        self.drop_tex=self.texture(2,'droplet')
        # Reuse book material itself for the last-page phenotype.
        self.page_tex=self.book_tex[:,self.book_tex.shape[1]//2:].copy()
        self.page_tex[:,:,3]=np.maximum(self.page_tex[:,:,3],.88)
        yy,xx=np.mgrid[:self.page_tex.shape[0],:self.page_tex.shape[1]]
        self.ink=np.exp(-((xx/self.page_tex.shape[1]-.52)**2/.034+
                         (yy/self.page_tex.shape[0]-.57)**2/.016)).astype('float32')
        self.ink*=.85+.15*np.sin(xx*.12)*np.cos(yy*.09)
        self.retained_transition=None

    def texture(self,scene,role):
        rgba=self.memories.assets[(scene,role)].copy()
        # One restrained material/light adaptation; source detail is retained.
        rgba[:,:,:3]=np.power(np.clip(rgba[:,:,:3],0,1),.94)
        return rgba

    def mesh(self,texture,quad,world,kind,maturity=1.,bend=0.,turn=0.,ink=0.,reflection=True,opacity=1.):
        """Rasterize a connected growing surface, not a moving RGBA rectangle.

        All UV controls extend from the parent spine/body axis; nonuniform
        growth and curvature are geometry. Material alpha only follows source
        transparency and final light transport.
        """
        if maturity<=.0001:return
        g=world.genes.get(kind,world.genes['journal'])
        nodes=world.node_amount.get(kind,3.)
        rows,cols=7,7
        u,v=np.meshgrid(np.linspace(0,1,cols),np.linspace(0,1,rows))
        uv=np.stack((u,v),axis=-1)
        q=np.asarray(quad,float)*[self.w,self.h]
        dest=(1-u[...,None])*(1-v[...,None])*q[0]+u[...,None]*(1-v[...,None])*q[1]+u[...,None]*v[...,None]*q[2]+(1-u[...,None])*v[...,None]*q[3]
        root=(1-v[...,None])*mix(q[0],q[1],.5)+v[...,None]*mix(q[3],q[2],.5)
        # Structure originates at a spine for paper, center body for a figure.
        birth=np.abs(u-.5)*(.24+.10*g[0])+abs(v-.5)*.13
        expansion=ease(np.clip((maturity-birth)/(1-birth),0,1))
        dest=root+(dest-root)*expansion[...,None]
        center=q.mean(axis=0)
        dest[...,1]=center[1]+(dest[...,1]-center[1])*ease(min(1,maturity*1.45))
        wave=np.sin(v*np.pi*(1+nodes*.12)+g[1]*2)*np.sin(u*np.pi)
        dest[...,0]+=wave*(g[2]-.5)*self.w*.018*maturity
        dest[...,1]+=np.sin(u*np.pi)*np.sin(v*np.pi)*(g[3]-.5)*self.h*.022*maturity
        if kind=='figure':
            reach=world.channels.get('reach',0)*(1-world.transition*.55)
            arm=(1-ease((u-.23)/.25))*ease((v-.25)/.25)
            dest[...,0]-=arm*reach*self.w*.18
            dest[...,1]+=arm*reach*self.h*.14
            if world.events and world.events.enabled('hand_pool') and world.enabled['story']:
                touch=float(ease((world.time-112)/18))
                dest[...,0]+=arm*touch*self.w*.027
                dest[...,1]+=arm*touch*self.h*.21
            breathing=(.45+.4*world.audio[0])*math.sin(world.time*.33)*self.h*.002
            dest[...,1]+=breathing
        if turn:
            # Spine is the left edge, free edge travels through a curved arc.
            span=np.linalg.norm(q[1]-q[0]);theta=turn*math.pi
            dest[...,0]-=u*span*(1-math.cos(theta))
            dest[...,1]-=np.sin(u*np.pi/2)*math.sin(theta)*self.h*.13
        dest[...,1]+=np.sin(u*np.pi*.5)*bend*self.h*.032
        # One extra connected fold grows for each selected structural node;
        # fractional node counts avoid topology-change flashes.
        for n in range(2,6):
            amount=float(ease(nodes-n))
            dest[...,1]+=amount*np.sin(u*np.pi*n)*np.sin(v*np.pi)*self.h*.0028
        rgba=texture.copy()
        if ink:
            ih,iw=rgba.shape[:2]
            stain=cv2.resize(self.ink,(iw,ih))
            rgba[:,:,:3]*=(1-stain[:,:,None]*ink*.87)
        self.draw_mesh(rgba,uv.reshape(-1,2),dest.reshape(-1,2),rows,cols,opacity,reflection,kind)
        self.mesh_faces+=(rows-1)*(cols-1)*2

    def draw_mesh(self,rgba,uv,dest,rows,cols,opacity,reflection,kind):
        x0=max(0,int(dest[:,0].min())-3);x1=min(self.w,int(dest[:,0].max())+4)
        y0=max(0,int(dest[:,1].min())-3);y1=min(self.h,int(dest[:,1].max())+4)
        if x1<=x0 or y1<=y0:return
        shape=(y1-y0,x1-x0)
        mapx=np.full(shape,-1,np.float32);mapy=np.full(shape,-1,np.float32)
        p=(dest-[x0,y0]).astype('float32')
        src=(uv*[rgba.shape[1]-1,rgba.shape[0]-1]).astype('float32')
        for row in range(rows-1):
            for col in range(cols-1):
                a=row*cols+col
                for ids in ([a,a+1,a+cols],[a+1,a+cols+1,a+cols]):
                    d=p[ids];s=src[ids]
                    if abs(np.linalg.det(np.stack((d[1]-d[0],d[2]-d[0]))))<.02:continue
                    lx=max(0,int(d[:,0].min()));rx=min(shape[1],int(d[:,0].max())+2)
                    ty=max(0,int(d[:,1].min()));by=min(shape[0],int(d[:,1].max())+2)
                    if rx<=lx or by<=ty:continue
                    affine=cv2.getAffineTransform(d,s)
                    yy,xx=np.mgrid[ty:by,lx:rx].astype('float32')
                    mask=np.zeros((by-ty,rx-lx),np.uint8)
                    cv2.fillConvexPoly(mask,np.rint(d-[lx,ty]).astype('int32'),1)
                    loc=mask>0
                    mapx[ty:by,lx:rx][loc]=(affine[0,0]*xx+affine[0,1]*yy+affine[0,2])[loc]
                    mapy[ty:by,lx:rx][loc]=(affine[1,0]*xx+affine[1,1]*yy+affine[1,2])[loc]
        # Premultiplication prevents transparent white edge halos.
        premult=rgba.copy();premult[:,:,:3]*=premult[:,:,3:4]
        warped=cv2.remap(premult,mapx,mapy,cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT)
        alpha=warped[:,:,3]
        light=self.canvas[y0:y1,x0:x1].mean(axis=(0,1))
        color=warped[:,:,:3]
        gain=np.array([.64,.70,.72]) if kind!='figure' else np.array([.66,.70,.74])
        color=color*gain+alpha[:,:,None]*light*(.17 if kind!='figure' else .27)
        alpha=cv2.GaussianBlur(alpha,(0,0),.55)
        color=cv2.GaussianBlur(color,(0,0),.55)
        if reflection:
            # Reflection is projected from the same deformed surface. It shares
            # the floor contact plane and is softer/darker than the real form.
            rh=max(2,round(shape[0]*(.28 if kind!='figure' else .45)))
            reflected=cv2.resize(np.flipud(color),(shape[1],rh))
            ra=cv2.resize(np.flipud(alpha),(shape[1],rh))*.17
            ry=min(self.h-1,int(y1 if kind!='figure' else self.h*.80))
            n=min(rh,self.h-ry)
            if n>0:
                fade=np.linspace(1,0,rh)[:n,None]
                target=self.canvas[ry:ry+n,x0:x1]
                target[:]=target*(1-ra[:n,:,None]*fade[:,:,None])+reflected[:n]*.17*fade[:,:,None]
        region=self.canvas[y0:y1,x0:x1]
        if kind in ('journal','record'):
            shadow=cv2.GaussianBlur(alpha,(0,0),3.)*.12
            region*=1-shadow[:,:,None]
        region[:]=region*(1-alpha[:,:,None]*opacity)+color*opacity

    def background(self,world):
        g=world.genes['space'];time=world.time;q=world.transition
        recede=world.channels.get('recede',0)
        # Loudness and onset-rate are continuous influences, not hard cuts.
        dilation=.045*recede+.024*world.audio[0]+.20*world.onset_rate*world.channels.get('audio_space',0)
        cx,cy=.52*self.w,.49*self.h
        dx=(self.xx-cx)*(1+dilation);dy=(self.yy-cy)*(1+dilation)
        corridor=(.5+.5*np.cos((self.x-.5)*np.pi))
        drift=(g[0]-.5)*self.w*.025*np.sin(self.y*np.pi)
        mx=(cx+dx+drift).astype('float32');my=(cy+dy).astype('float32')
        old=cv2.remap(self.backgrounds[0],mx,my,cv2.INTER_LINEAR,borderMode=cv2.BORDER_REFLECT_101)
        # A persistent field of old wall/floor evidence changes the next scene's
        # local growth times. No reset at 65s, and no uniform crossfade.
        if self.last_time is None:
            gray=cv2.cvtColor(old,cv2.COLOR_RGB2GRAY)
            self.trace=cv2.GaussianBlur(abs(cv2.Sobel(gray,cv2.CV_32F,1,0)),(0,0),4)
            self.trace/=max(float(self.trace.max()),.01)
        retained=(self.trace*.30+cv2.resize(world.memory_field,(self.w,self.h))*.70) if world.memory_enabled else np.zeros_like(self.trace)
        local=(time-65)/20
        distance=np.sqrt(((self.x-.52)/.67)**2+((self.y-.48)/.71)**2)
        delay=.025+.52*distance+.20*self.front+.12*retained
        # A connected front extends out of the remembered vanishing region.
        # Only a narrow neighbourhood mixes material at once, unlike a full
        # frame opacity crossfade. Matched displacement morphs local geometry.
        progress=ease((local-delay)/.23)
        growth=np.asarray(progress,np.float32)
        old=cv2.remap(self.backgrounds[0],(mx+growth*self.flow[1][:,:,0]).astype('float32'),
            (my+growth*self.flow[1][:,:,1]).astype('float32'),cv2.INTER_LINEAR,borderMode=cv2.BORDER_REFLECT_101)
        # Room surfaces open and stretch toward the next corridor's vanishing
        # region before their material develops; neither complete frame cuts in.
        stretch=(1-growth)*(.065+.035*g[1])
        bx=(self.xx+(self.xx-cx)*stretch+drift*.5).astype('float32')
        by=(self.yy+(self.yy-cy)*stretch).astype('float32')
        new=cv2.remap(self.backgrounds[1],(bx+(1-growth)*self.flow[0][:,:,0]).astype('float32'),
            (by+(1-growth)*self.flow[0][:,:,1]).astype('float32'),cv2.INTER_LINEAR,borderMode=cv2.BORDER_REFLECT_101)
        base=old*(1-growth[:,:,None])+new*growth[:,:,None]
        # Hierarchical births are spatial regions, not particle emission.
        maturity=ease((world.development_time-2)/34)
        delay0=.12*abs(self.x-.5)+.18*abs(self.y-.58)+.08*self.front
        spread=ease((maturity-delay0)/.73).astype('float32')
        dark=np.array([.035,.043,.051],np.float32)
        self.canvas=dark+(base-dark)*spread[:,:,None]
        # Mutated bay count bends spatial development; coherent, slow changes.
        bays=world.node_amount['space']
        wav=(g[2]-.5)*np.sin(self.y*np.pi*bays)*self.w*.004
        self.canvas=cv2.remap(self.canvas,(self.xx+wav).astype('float32'),self.yy,cv2.INTER_LINEAR,borderMode=cv2.BORDER_REFLECT_101)
        self.canvas=np.power(np.clip(self.canvas,0,1),.83)
        self.canvas*=np.array([.92,1.015,1.03],np.float32)
        fog=np.exp(-((self.x-.55)**2/.13+(self.y-.45)**2/.18))*.10
        self.canvas=self.canvas*(1-fog[:,:,None])+np.array([.36,.43,.45])*fog[:,:,None]
        self.canvas=self.canvas.astype('float32')
        self.stats={'background_growth':float(maturity),'incoming_area':float(growth.mean()),
            'room_dilation':float(dilation),'trace_checksum':float(retained.sum())}
        self.last_time=time

    def render(self,world):
        self.mesh_faces=0;self.background(world)
        t=world.time;q=world.transition
        # Same incoming surface continues to receive the first-scene figure.
        fg=world.genes['figure']
        slide=world.channels.get('glide',0)*.09
        float_y=.025*world.channels.get('float',0)
        quad=np.array([[.535-slide,.27-float_y],[.76-slide,.27-float_y],
                       [.75-slide,.74-float_y],[.535-slide,.74-float_y]])
        # Keep Team3's actual first shadow; transition bends its long limbs,
        # rather than switching to an unrelated stock human silhouette.
        self.mesh(self.figure_tex,quad,world,'figure',world.maturity('figure'),reflection=True)
        # A source-coloured wet material connected to the floor, not a diamond
        # floating at full source aspect ratio.
        poolq=np.array([[.47,.814],[.68,.814],[.70,.867],[.45,.867]])
        rise=world.channels.get('hand_pool',0)*.007
        poolq[:,1]-=rise
        self.mesh(self.pool_tex,poolq,world,'pool',world.maturity('pool'),reflection=False,opacity=.48)
        # Original supplied journal, rooted at the floor with shared illumination.
        bookq=np.array([[.222,.769],[.455,.748],[.486,.876],[.205,.909]])
        self.mesh(self.book_tex,bookq,world,'journal',world.maturity('journal'),reflection=True)
        # The same last-page geometry exists before and after the scene boundary.
        turn=world.channels.get('page_turn',0)
        ink=1-world.channels.get('erase',0)
        transfer=float(ease((t-74)/16))
        self.mesh(self.page_tex,world.page_points,world,'journal',world.maturity('journal'),
                  turn=turn*(1-transfer),ink=ink,reflection=True)
        # Additional record faces branch from the retained page rather than
        # appearing as a completed new object. Their source is scene-two PNG.
        amount=world.node_amount['record']
        growth=float(ease((world.incoming_development-5)/24))
        for layer in reversed(range(1,int(math.ceil(amount))+1)):
            develop=growth*float(ease(amount-layer+1))
            offset=np.array([.005*layer,-.008*layer])*growth
            writing=0.
            if t>=96 and world.enabled['story'] and world.events.enabled('writing'):
                writing=(1-world.channels.get('flutter',0))*(1-world.channels.get('erase_before_water',0))
            self.mesh(self.record_tex,world.page_points+offset,world,'record',develop,
                      bend=world.channels.get('flutter',0)*.65,ink=writing,reflection=True,opacity=.86)
        if world.channels.get('drop',0):
            # An actual source-derived droplet surface falls and disappears at
            # floor contact. No invented impact audio is mixed into the WAV.
            cycle=((t-75)/4.5)%1
            y=.17+.63*float(ease(cycle))
            s=.016*(1-float(ease((cycle-.87)/.13)))
            dq=np.array([[.525-s,y-s],[.525+s,y-s],[.525+s,y+s*1.8],[.525-s,y+s*1.8]])
            self.mesh(self.drop_tex,dq,world,'record',1.,reflection=False,opacity=.60)
        # Later scene-two channels are implemented but never accelerated into
        # this 65-85s excerpt.
        if t>=96:
            fade=world.channels.get('writing',0)
            erased=world.channels.get('erase_before_water',0)
            self.stats['record_ink_strength']=(1-fade)*(1-erased)
        light=np.maximum(self.canvas-.66,0)
        frame=self.canvas+cv2.GaussianBlur(light,(0,0),3.)*.12
        frame*=1-.08*((self.x-.5)**2+(self.y-.5)**2)[:,:,None]
        self.stats.update({'mesh_faces':self.mesh_faces,'turn_radians':turn*math.pi,
            'ink_remaining':ink,'record_development':growth,'pool_height_delta':rise,
            'page_control_points':world.page_points.tolist()})
        self.frame_count+=1
        return (np.clip(frame,0,1)*255).astype('uint8')
